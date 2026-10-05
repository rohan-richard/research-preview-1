import base64
import json
import logging
import secrets
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from html import escape
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.orm import Session, selectinload, undefer
from standardwebhooks import Webhook, WebhookVerificationError

from app import care_plans, chat_server, fhir_map
from app.audit import Audit
from app.auth import DB, Auth
from app.clock import iso, now
from app.errors import ApiError
from app.idempotency import Idempotent
from app.logs import decode_cursor, encode_cursor
from app.models import (
    Allergy,
    CarePlan,
    CarePlanGoal,
    CareTeamMember,
    Condition,
    EhrConnection,
    EhrSyncJob,
    Encounter,
    FhirResource,
    Job,
    Journey,
    LabReport,
    LabResult,
    Medication,
    MedicationFill,
    Profile,
    WebhookEvent,
)
from app.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/ehr")
integrations_router = APIRouter(prefix="/v1/integrations/fasten")

IN_PROGRESS = ("requested", "downloading")
RESYNC_AFTER = timedelta(hours=24)
STALE_REQUEST = timedelta(hours=1)
FASTEN_STATUS = {"authorized": "connected", "revoked": "revoked", "refreshing": "pending"}
EXPORT_EVENTS = ("patient.ehi_export_success", "patient.ehi_export_failed")
RECORD_TABLES = (MedicationFill, LabResult, LabReport, Medication, Condition, Allergy, Encounter, CareTeamMember)

# The API answers fast. A record export file can take a while to arrive.
fasten = httpx.Client(timeout=httpx.Timeout(30, read=120))

Limit = Annotated[int, Query(ge=1, le=200)]

STITCH_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect your health system</title>
<link rel="stylesheet" href="https://cdn.fastenhealth.com/connect/v4/fasten-stitch-element.css">
<script type="module" src="https://cdn.fastenhealth.com/connect/v4/fasten-stitch-element.js"></script>
</head>
<body style="margin:0">
<fasten-stitch-element public-id="{public_id}"></fasten-stitch-element>
<script nonce="{nonce}">
function forward(text) {
  var bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.fasten;
  if (bridge) {
    bridge.postMessage(text);
  } else if (window.parent !== window) {
    window.parent.postMessage(text, "*");
  }
}
document.querySelector("fasten-stitch-element").addEventListener("eventBus", function (event) {
  // The element re-emits the iframe's MessageEvent, so the JSON text is in detail.data.
  var data = event.detail;
  if (data && data.data !== undefined) { data = data.data; }
  forward(typeof data === "string" ? data : JSON.stringify(data));
});
var params = new URLSearchParams(window.location.search);
if (params.get("org_connection_id")) {
  forward(JSON.stringify({event_type: "widget.complete", data: [{org_connection_id: params.get("org_connection_id"), endpoint_id: params.get("endpoint_id"), platform_type: params.get("platform_type")}]}));
}
</script>
</body>
</html>
"""
STITCH_CSP = "; ".join(
    [
        "default-src 'none'",
        "script-src https://cdn.fastenhealth.com 'nonce-{nonce}'",
        "style-src https://cdn.fastenhealth.com 'unsafe-inline'",
        "connect-src https://*.fastenhealth.com",
        "img-src https://*.fastenhealth.com data:",
        "font-src https://cdn.fastenhealth.com data:",
        "frame-src https://*.fastenhealth.com",
        "base-uri 'none'",
        "form-action 'none'",
    ]
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionPost(Strict):
    org_connection_id: str = Field(min_length=1, max_length=200)
    organization: str = Field(min_length=1, max_length=200)
    platform_type: str | None = Field(default=None, min_length=1, max_length=50)


class FastenError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class EhrError(Exception):
    pass


def fasten_auth() -> tuple[str, str]:
    if not settings.fasten_public_id or not settings.fasten_private_key:
        raise FastenError("FASTEN_PUBLIC_ID or FASTEN_PRIVATE_KEY is not set")
    return settings.fasten_public_id, settings.fasten_private_key


def fasten_call(method: str, path: str, body: dict | None = None) -> dict:
    try:
        reply = fasten.request(method, settings.fasten_api_url.rstrip("/") + path, json=body, auth=fasten_auth())
    except httpx.HTTPError as exc:
        raise FastenError(f"{method} {path}: {exc}", retryable=True) from exc
    if reply.status_code // 100 != 2:
        raise FastenError(f"{method} {path} returned {reply.status_code}: {reply.text[:200]}", retryable=reply.status_code >= 500)
    try:
        data = reply.json().get("data")
    except (ValueError, AttributeError):
        data = None
    if not isinstance(data, dict):
        raise FastenError(f"{method} {path} returned no data")
    return data


def org_connection(org_connection_id: str) -> dict:
    return fasten_call("GET", f"/bridge/org_connection/{org_connection_id}")


def request_export(org_connection_id: str) -> dict:
    return fasten_call("POST", "/bridge/fhir/ehi-export", {"org_connection_id": org_connection_id})


def download_resources(url: str, handle: Callable[[dict], None]) -> int:
    # The credentials go to the Fasten API only. It redirects to a signed link on another host.
    auth = fasten_auth() if url.startswith(settings.fasten_api_url.rstrip("/")) else None
    skipped = 0
    try:
        with fasten.stream("GET", url, auth=auth, follow_redirects=True) as reply:
            if reply.status_code != 200:
                raise FastenError(f"download returned {reply.status_code}")
            for line in reply.iter_lines():
                if not line.strip():
                    continue
                try:
                    resource = json.loads(line)
                except ValueError:
                    resource = None
                if not isinstance(resource, dict) or not resource.get("resourceType") or resource.get("id") is None:
                    skipped += 1
                    continue
                handle(resource)
    except httpx.HTTPError as exc:
        raise FastenError(f"download: {exc}") from exc
    return skipped


def latest_job(db: Session, connection_id: uuid.UUID) -> EhrSyncJob | None:
    return db.scalar(
        select(EhrSyncJob)
        .where(EhrSyncJob.connection_id == connection_id)
        .order_by(EhrSyncJob.requested_at.desc(), EhrSyncJob.id.desc())
        .limit(1)
    )


def job_in_progress(db: Session, connection_id: uuid.UUID) -> EhrSyncJob | None:
    return db.scalar(
        select(EhrSyncJob)
        .where(EhrSyncJob.connection_id == connection_id, EhrSyncJob.status.in_(IN_PROGRESS))
        .order_by(EhrSyncJob.requested_at.desc(), EhrSyncJob.id.desc())
        .limit(1)
    )


def sync_job_for(db: Session, connection: EhrConnection, task_id) -> EhrSyncJob | None:
    if task_id:
        job = db.scalar(select(EhrSyncJob).where(EhrSyncJob.connection_id == connection.id, EhrSyncJob.external_task_id == str(task_id)))
        if job is not None:
            return job
    return job_in_progress(db, connection.id)


def start_sync(db: Session, connection: EhrConnection) -> EhrSyncJob:
    job = EhrSyncJob(connection_id=connection.id)
    db.add(job)
    db.flush()
    # Not jobs.enqueue: app/jobs.py imports this module for the handlers.
    db.add(Job(kind="ehr_export", payload={"sync_job_id": str(job.id)}))
    return job


def fail_job(job: EhrSyncJob, error: str) -> None:
    job.status = "failed"
    job.error = error[:2000]
    job.completed_at = now()


def revoke(db: Session, connection: EhrConnection, reason: str) -> None:
    connection.status = "revoked"
    connection.revoked_at = now()
    for job in db.scalars(select(EhrSyncJob).where(EhrSyncJob.connection_id == connection.id, EhrSyncJob.status.in_(IN_PROGRESS))):
        fail_job(job, reason)


def apply_details(connection: EhrConnection, details: dict) -> None:
    if isinstance(details.get("scope"), str):
        connection.scope = details["scope"]
    if fhir_map.when(details.get("consent_expires_at")):
        connection.consent_expires_at = fhir_map.when(details["consent_expires_at"])
    if connection.platform_type is None and isinstance(details.get("platform_type"), str):
        connection.platform_type = details["platform_type"]
    status = FASTEN_STATUS.get(details.get("status") or details.get("connection_status"))
    if status == "revoked":
        connection.revoked_at = now()
    if status:
        connection.status = status


def catalog_name(brand_id: str) -> str | None:
    # The catalog is public: it takes the public id, never the private key.
    mode = "test" if settings.fasten_public_id.startswith("public_test_") else "live"
    try:
        reply = fasten.get(settings.fasten_api_url.rstrip("/") + "/bridge/catalog",
                           params={"api_mode": mode, "public_id": settings.fasten_public_id, "brand_id": brand_id})
        data = reply.json().get("data") if reply.status_code == 200 else None
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else None


def fill_details(connection: EhrConnection) -> None:
    try:
        details = org_connection(connection.org_connection_id)
    except FastenError as exc:
        logger.warning("could not read Fasten connection %s: %s", connection.org_connection_id, exc)
        return
    apply_details(connection, details)
    if details.get("catalog_brand_id"):
        name = catalog_name(str(details["catalog_brand_id"]))
        if name:
            connection.organization = name


def connection_out(connection: EhrConnection, job: EhrSyncJob | None) -> dict:
    return {
        "id": str(connection.id),
        "organization": connection.organization,
        "platform_type": connection.platform_type,
        "status": connection.status,
        "last_synced_at": iso(connection.last_synced_at),
        "sync": {"status": job.status if job else None, "error": job.error if job else None},
    }


def load_connection(db: Session, user_id: uuid.UUID, connection_id: uuid.UUID) -> EhrConnection:
    connection = db.get(EhrConnection, connection_id)
    if connection is None or connection.user_id != user_id:
        raise ApiError(404, "not_found", "No connection with that id.")
    return connection


def code_out(row) -> dict:
    return {"system": row.code_system, "code": row.code, "display": row.display}


def source_out(row) -> dict:
    return resource_source(row.resource)


def resource_source(resource: FhirResource) -> dict:
    return {
        "connection_id": str(resource.connection_id),
        "organization": resource.connection.organization,
        "fhir_type": resource.resource_type,
        "last_updated": iso(resource.last_updated),
    }


def with_source(query, model):
    return query.options(selectinload(model.resource).selectinload(FhirResource.connection))


def number_out(value) -> float | None:
    return float(value) if value is not None else None


def day_out(value: date | None) -> str | None:
    return value.isoformat() if value else None


def value_out(row: LabResult):
    return number_out(row.value_number) if row.value_number is not None else row.value_text


def condition_out(row: Condition) -> dict:
    return {
        "id": str(row.id),
        "code": code_out(row),
        "clinical_status": row.clinical_status,
        "onset_date": day_out(row.onset_date),
        "abatement_date": day_out(row.abatement_date),
        "source": source_out(row),
    }


def allergy_out(row: Allergy) -> dict:
    return {
        "id": str(row.id),
        "code": code_out(row),
        "criticality": row.criticality,
        "reaction": row.reaction,
        "clinical_status": row.clinical_status,
        "source": source_out(row),
    }


def medication_out(row: Medication, next_refill: date | None) -> dict:
    return {
        "id": str(row.id),
        "code": code_out(row),
        "status": row.status,
        "dose_text": row.dose_text,
        "start_date": day_out(row.start_date),
        "end_date": day_out(row.end_date),
        "prescriber": row.prescriber,
        "next_refill_date": day_out(next_refill),
        "source": source_out(row),
    }


def fill_out(fill: MedicationFill) -> dict:
    return {
        "dispensed_at": iso(fill.dispensed_at),
        "quantity": number_out(fill.quantity),
        "days_supply": fill.days_supply,
        "pharmacy": fill.pharmacy,
        "expected_refill_date": day_out(fill.expected_refill_date),
    }


def lab_item_out(row: LabResult, count: int) -> dict:
    return {
        "code": code_out(row),
        "category": row.category,
        "latest": {"value": value_out(row), "unit": row.unit, "interpretation": row.interpretation, "effective_at": iso(row.effective_at)},
        "count": count,
    }


def encounter_out(row: Encounter) -> dict:
    return {
        "id": str(row.id),
        "class": row.encounter_class,
        "type": row.type,
        "start_at": iso(row.start_at),
        "end_at": iso(row.end_at),
        "practitioner": row.practitioner,
        "organization": row.organization,
        "reason": row.reason,
        "source": source_out(row),
    }


def member_out(row: CareTeamMember) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "role": row.role,
        "organization": row.organization,
        "npi": row.npi,
        "phone": row.phone,
        "source": source_out(row),
    }


def encode_key(first: str | None, second) -> str:
    return base64.urlsafe_b64encode(f"{first or ''}|{second}".encode()).decode()


def decode_key(cursor: str) -> tuple[str, str]:
    try:
        first, second = base64.urlsafe_b64decode(cursor.encode()).decode().rsplit("|", 1)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ApiError(400, "invalid_request", "cursor is not valid.") from exc
    return first, second


def by_display(query, model, cursor: str | None):
    key = func.coalesce(model.display, "")
    query = query.order_by(key, model.id)
    if cursor:
        display, row_id = decode_key(cursor)
        try:
            row_id = uuid.UUID(row_id)
        except ValueError as exc:
            raise ApiError(400, "invalid_request", "cursor is not valid.") from exc
        query = query.where(tuple_(key, model.id) > tuple_(display, row_id))
    return query


def display_key(row) -> str:
    return encode_key(row.display, row.id)


def page_out(rows: list, limit: int, out: Callable, cursor_of: Callable) -> dict:
    page = rows[:limit]
    return {"items": [out(row) for row in page], "next_cursor": cursor_of(page[-1]) if len(rows) > limit else None}


@router.get("/connections")
def list_connections(auth: Auth, db: DB) -> dict:
    user, _ = auth
    rows = db.scalars(select(EhrConnection).where(EhrConnection.user_id == user.id).order_by(EhrConnection.created_at, EhrConnection.id))
    return {"items": [connection_out(row, latest_job(db, row.id)) for row in rows]}


@router.post("/connections", status_code=201)
def add_connection(body: ConnectionPost, auth: Auth, db: DB, audit: Audit, idempotency: Idempotent) -> dict:
    # Imported here: app.me imports app.jobs, and app.jobs imports this module for the handlers.
    from app.me import current_consents

    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    if not current_consents(db, user.id)["health_records"]:
        raise ApiError(409, "consent_required", "Allow the health_records consent first.", scope="health_records")
    connection = db.scalar(
        select(EhrConnection).where(EhrConnection.source == "fasten", EhrConnection.org_connection_id == body.org_connection_id)
    )
    if connection is not None and (connection.user_id != user.id or connection.status != "revoked"):
        raise ApiError(409, "already_connected", "This health system is already connected.")
    if connection is None:
        connection = EhrConnection(user_id=user.id, org_connection_id=body.org_connection_id)
        db.add(connection)
    connection.organization = body.organization
    connection.platform_type = body.platform_type
    connection.status = "pending"
    connection.revoked_at = None
    connection.connected_at = now()
    fill_details(connection)
    db.flush()
    job = start_sync(db, connection)
    out = connection_out(connection, job)
    audit.record("create", "ehr_connections", connection.id)
    idempotency.store(201, out)
    db.commit()
    return out


@router.post("/connections/{connection_id}/sync", status_code=202)
def sync_connection(connection_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    connection = load_connection(db, user.id, connection_id)
    if connection.status == "revoked":
        raise ApiError(409, "connection_revoked", "This health system is disconnected. Connect it again.")
    if job_in_progress(db, connection.id) is not None:
        raise ApiError(409, "sync_in_progress", "A sync is already running.")
    job = start_sync(db, connection)
    audit.record("update", "ehr_connections", connection.id)
    db.commit()
    return {"sync": {"status": job.status}}


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: uuid.UUID, auth: Auth, db: DB, audit: Audit, delete_data: bool = False) -> None:
    user, _ = auth
    connection = load_connection(db, user.id, connection_id)
    revoke(db, connection, "The patient disconnected this health system.")
    if delete_data:
        # Care plans have no foreign key to fhir_resources, so they do not cascade.
        owned = select(FhirResource.id).where(FhirResource.connection_id == connection.id)
        db.execute(delete(CarePlan).where(CarePlan.fhir_resource_id.in_(owned)))
        db.execute(delete(FhirResource).where(FhirResource.connection_id == connection.id))
    audit.record("delete", "ehr_connections", connection.id)
    db.commit()


@router.get("/summary")
def summary(auth: Auth, db: DB) -> dict:
    user, _ = auth
    connections = db.scalars(select(EhrConnection).where(EhrConnection.user_id == user.id)).all()
    synced = [row.last_synced_at for row in connections if row.last_synced_at]

    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.user_id == user.id))

    def count_raw(resource_type: str) -> int:
        return db.scalar(select(func.count()).select_from(FhirResource).where(*live_raw(user.id, resource_type)))

    return {
        "connected": any(row.status != "revoked" for row in connections),
        "last_synced_at": iso(max(synced)) if synced else None,
        "counts": {
            "conditions": count(Condition),
            "allergies": count(Allergy),
            "medications": count(Medication),
            "lab_types": db.scalar(select(func.count(func.distinct(LabResult.code))).where(LabResult.user_id == user.id)),
            "encounters": count(Encounter),
            "immunizations": count_raw("Immunization"),
            "procedures": count_raw("Procedure"),
            "documents": count_raw("DocumentReference"),
        },
    }


@router.get("/conditions")
def list_conditions(
    auth: Auth, db: DB, audit: Audit, status: Literal["active", "resolved", "all"] = "active", limit: Limit = 50, cursor: str | None = None
) -> dict:
    user, _ = auth
    query = with_source(select(Condition).where(Condition.user_id == user.id), Condition).limit(limit + 1)
    if status != "all":
        query = query.where(Condition.clinical_status == status)
    rows = db.scalars(by_display(query, Condition, cursor)).all()
    audit.record("read", "conditions")
    db.commit()
    return page_out(rows, limit, condition_out, display_key)


@router.get("/allergies")
def list_allergies(auth: Auth, db: DB, audit: Audit, limit: Limit = 50, cursor: str | None = None) -> dict:
    user, _ = auth
    query = with_source(select(Allergy).where(Allergy.user_id == user.id), Allergy).limit(limit + 1)
    rows = db.scalars(by_display(query, Allergy, cursor)).all()
    audit.record("read", "allergies")
    db.commit()
    return page_out(rows, limit, allergy_out, display_key)


@router.get("/medications")
def list_medications(
    auth: Auth, db: DB, audit: Audit, status: Literal["active", "stopped", "all"] = "active", limit: Limit = 50, cursor: str | None = None
) -> dict:
    user, _ = auth
    refills = (
        select(MedicationFill.medication_id, func.max(MedicationFill.expected_refill_date).label("next_refill"))
        .group_by(MedicationFill.medication_id)
        .subquery()
    )
    query = with_source(
        select(Medication, refills.c.next_refill)
        .outerjoin(refills, refills.c.medication_id == Medication.id)
        .where(Medication.user_id == user.id),
        Medication,
    ).limit(limit + 1)
    if status == "active":
        query = query.where(Medication.status == "active")
    elif status == "stopped":
        query = query.where(Medication.status != "active")
    rows = db.execute(by_display(query, Medication, cursor)).all()
    audit.record("read", "medications")
    db.commit()
    return page_out(rows, limit, lambda row: medication_out(row[0], row[1]), lambda row: display_key(row[0]))


@router.get("/medications/{medication_id}")
def get_medication(medication_id: uuid.UUID, auth: Auth, db: DB) -> dict:
    user, _ = auth
    row = db.get(Medication, medication_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "No medication with that id.")
    fills = db.scalars(
        select(MedicationFill)
        .where(MedicationFill.medication_id == row.id)
        .order_by(MedicationFill.dispensed_at.desc().nulls_last(), MedicationFill.id)
    ).all()
    next_refill = max((fill.expected_refill_date for fill in fills if fill.expected_refill_date), default=None)
    return medication_out(row, next_refill) | {
        "quantity": number_out(row.quantity),
        "refills_allowed": row.refills_allowed,
        "days_supply": row.days_supply,
        "fills": [fill_out(fill) for fill in fills],
    }


@router.get("/labs")
def list_labs(auth: Auth, db: DB, audit: Audit, limit: Limit = 50, cursor: str | None = None) -> dict:
    user, _ = auth
    latest = db.scalars(
        with_source(select(LabResult).where(LabResult.user_id == user.id), LabResult)
        .distinct(LabResult.code)
        .order_by(LabResult.code, LabResult.effective_at.desc().nulls_last(), LabResult.id.desc())
    ).all()
    counts = dict(db.execute(select(LabResult.code, func.count()).where(LabResult.user_id == user.id).group_by(LabResult.code)).all())
    items = sorted(latest, key=lambda row: (row.display or "", row.code or ""))
    if cursor:
        key = decode_key(cursor)
        items = [row for row in items if (row.display or "", row.code or "") > key]
    audit.record("read", "lab_results")
    db.commit()
    return page_out(items[: limit + 1], limit, lambda row: lab_item_out(row, counts.get(row.code, 0)), lambda row: encode_key(row.display, row.code))


@router.get("/labs/{code}")
def lab_series(
    code: str, auth: Auth, db: DB, start: Annotated[date | None, Query(alias="from")] = None, to: date | None = None
) -> dict:
    user, _ = auth
    rows = db.scalars(
        select(LabResult)
        .where(LabResult.user_id == user.id, LabResult.code == code)
        .order_by(LabResult.effective_at.nulls_last(), LabResult.id)
    ).all()
    if not rows:
        raise ApiError(404, "not_found", "No lab results with that code.")
    dated = [row for row in rows if row.effective_at is not None]
    latest = dated[-1] if dated else rows[-1]
    points = [
        row
        for row in dated
        if (start is None or row.effective_at.date() >= start) and (to is None or row.effective_at.date() <= to)
    ]
    return {
        "code": code_out(latest),
        "category": latest.category,
        "unit": latest.unit,
        "range_low": number_out(latest.range_low),
        "range_high": number_out(latest.range_high),
        "points": [{"value": value_out(row), "effective_at": iso(row.effective_at)} for row in points],
    }


@router.get("/encounters")
def list_encounters(auth: Auth, db: DB, audit: Audit, limit: Limit = 50, cursor: str | None = None) -> dict:
    user, _ = auth
    query = (
        with_source(select(Encounter).where(Encounter.user_id == user.id), Encounter)
        .order_by(Encounter.start_at.desc(), Encounter.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(tuple_(Encounter.start_at, Encounter.id) < tuple_(*decode_cursor(cursor)))
    rows = db.scalars(query).all()
    audit.record("read", "encounters")
    db.commit()
    return page_out(rows, limit, encounter_out, lambda row: encode_cursor(row.start_at, row.id))


@router.get("/care-team")
def list_care_team(auth: Auth, db: DB, audit: Audit, limit: Limit = 50, cursor: str | None = None) -> dict:
    user, _ = auth
    query = with_source(select(CareTeamMember).where(CareTeamMember.user_id == user.id), CareTeamMember).limit(limit + 1)
    rows = db.scalars(by_display(query, CareTeamMember, cursor)).all()
    audit.record("read", "care_team_members")
    db.commit()
    return page_out(rows, limit, member_out, display_key)


def live_raw(user_id: uuid.UUID, resource_type: str) -> tuple:
    return FhirResource.user_id == user_id, FhirResource.resource_type == resource_type, FhirResource.removed_at.is_(None)


def raw_page(db: Session, user_id: uuid.UUID, resource_type: str, mapper: Callable, stamp: str, limit: int, cursor: str | None) -> dict:
    found = db.scalars(
        select(FhirResource)
        .where(*live_raw(user_id, resource_type))
        .options(undefer(FhirResource.resource), selectinload(FhirResource.connection))
    ).all()
    items = [(row, fields) for row in found if (fields := mapper(row.resource))]

    # The date lives in the raw JSON, so sort here. A patient has tens of these, not thousands.
    def key(item) -> tuple[str, str]:
        return iso(item[1][stamp]) or "", str(item[0].id)

    items.sort(key=key, reverse=True)
    if cursor:
        after = decode_key(cursor)
        items = [item for item in items if key(item) < after]

    def out(item) -> dict:
        row, fields = item
        return {"id": str(row.id), **{name: iso(value) if name == stamp else value for name, value in fields.items()}, "source": resource_source(row)}

    return page_out(items[: limit + 1], limit, out, lambda item: encode_key(*key(item)))


@router.get("/patient")
def get_patient(auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    row = db.scalars(
        select(FhirResource)
        .where(*live_raw(user.id, "Patient"))
        .options(undefer(FhirResource.resource))
        .order_by(FhirResource.last_updated.desc().nulls_last(), FhirResource.created_at.desc())
        .limit(1)
    ).first()
    fields = fhir_map.patient(row.resource) if row else None
    if fields is None:
        raise ApiError(404, "not_found", "No patient details in the imported records.")
    audit.record("read", "fhir_resources", row.id)
    db.commit()
    return fields | {"date_of_birth": day_out(fields["date_of_birth"])}


@router.get("/immunizations")
def list_immunizations(auth: Auth, db: DB, audit: Audit, limit: Limit = 50, cursor: str | None = None) -> dict:
    page = raw_page(db, auth[0].id, "Immunization", fhir_map.immunization, "occurred_at", limit, cursor)
    audit.record("read", "immunizations")
    db.commit()
    return page


@router.get("/procedures")
def list_procedures(auth: Auth, db: DB, audit: Audit, limit: Limit = 50, cursor: str | None = None) -> dict:
    page = raw_page(db, auth[0].id, "Procedure", fhir_map.procedure, "performed_at", limit, cursor)
    audit.record("read", "procedures")
    db.commit()
    return page


@router.get("/documents")
def list_documents(auth: Auth, db: DB, audit: Audit, limit: Limit = 50, cursor: str | None = None) -> dict:
    page = raw_page(db, auth[0].id, "DocumentReference", fhir_map.document, "date", limit, cursor)
    audit.record("read", "documents")
    db.commit()
    return page


def verify_webhook(raw: bytes, headers: dict) -> tuple[dict, bool]:
    verified = False
    if settings.fasten_webhook_secret:
        try:
            Webhook(settings.fasten_webhook_secret).verify(raw, headers, json_parse=False)
            verified = True
        except (WebhookVerificationError, ValueError):
            verified = False
    try:
        event = json.loads(raw)
    except ValueError:
        event = None
    if not isinstance(event, dict):
        event = {"raw": raw.decode(errors="replace")[:2000]}
    return event, verified


@integrations_router.post("/webhook")
async def fasten_webhook(request: Request, db: DB) -> Response:
    raw = await request.body()
    event, verified = verify_webhook(raw, dict(request.headers))
    external_id = str(event["id"]) if event.get("id") else str(uuid.uuid4())
    row = db.scalar(select(WebhookEvent).where(WebhookEvent.source == "fasten", WebhookEvent.external_id == external_id))
    if row is None:
        row = WebhookEvent(source="fasten", external_id=external_id, signature_verified=False, status="failed", payload={})
        db.add(row)
    # An unsigned request must not use up an id, so the real event with that id still gets in.
    if row.signature_verified:
        return Response(status_code=200)
    row.event_type = str(event.get("type") or "unknown")
    row.payload = event
    row.signature_verified = verified
    row.status = "received" if verified else "failed"
    row.error = None if verified else "The webhook signature is missing or wrong."
    db.flush()
    if verified:
        db.add(Job(kind="ehr_webhook", payload={"event_id": str(row.id)}))
    db.commit()
    if not verified:
        raise ApiError(401, "webhook_signature_invalid", "The webhook signature is missing or wrong.")
    return Response(status_code=200)


@integrations_router.get("/stitch", response_class=HTMLResponse)
def stitch_page() -> HTMLResponse:
    if not settings.fasten_public_id:
        raise ApiError(404, "not_found", "Fasten is not configured on this server.")
    nonce = secrets.token_urlsafe(16)
    page = STITCH_PAGE.replace("{public_id}", escape(settings.fasten_public_id)).replace("{nonce}", nonce)
    return HTMLResponse(page, headers={"Content-Security-Policy": STITCH_CSP.replace("{nonce}", nonce)})


def run_export(db: Session, payload: dict) -> None:
    job = db.get(EhrSyncJob, uuid.UUID(payload["sync_job_id"]))
    if job is None or job.status != "requested":
        return
    connection = db.get(EhrConnection, job.connection_id)
    if connection.status == "revoked":
        fail_job(job, "The connection is revoked.")
        return
    try:
        task = request_export(connection.org_connection_id)
    except FastenError as exc:
        # Fasten's test mode answers 500 now and then and succeeds a moment later; the job runner retries.
        if exc.retryable:
            raise
        fail_job(job, str(exc))
        return
    job.external_task_id = str(task["task_id"]) if task.get("task_id") else None
    # Fasten answers "success" at once when the export is already built, and the webhook with the
    # links still follows. Only a task this connection already imported has no webhook to wait for.
    imported_before = job.external_task_id and db.scalar(
        select(EhrSyncJob).where(
            EhrSyncJob.connection_id == connection.id,
            EhrSyncJob.external_task_id == job.external_task_id,
            EhrSyncJob.status == "done",
            EhrSyncJob.id != job.id,
        )
    ) is not None
    if task.get("status") == "success" and imported_before:
        job.status = "done"
        job.completed_at = now()
    elif task.get("status") == "failed":
        fail_job(job, "Fasten reported the export as failed.")


def import_export(db: Session, connection: EhrConnection, job: EhrSyncJob, data: dict) -> None:
    existing = {
        (row.resource_type, row.fhir_id): row
        for row in db.scalars(select(FhirResource).where(FhirResource.connection_id == connection.id))
    }
    seen: set[tuple[str, str]] = set()

    def keep(resource: dict) -> None:
        key = (str(resource["resourceType"]), str(resource["id"]))
        if key in seen:
            return
        seen.add(key)
        meta = resource.get("meta") if isinstance(resource.get("meta"), dict) else {}
        version = str(meta["versionId"]) if meta.get("versionId") is not None else None
        updated = fhir_map.when(meta.get("lastUpdated"))
        row = existing.get(key)
        if row is None:
            row = FhirResource(
                user_id=connection.user_id,
                connection_id=connection.id,
                resource_type=key[0],
                fhir_id=key[1],
                version_id=version,
                last_updated=updated,
                resource=resource,
            )
            db.add(row)
            existing[key] = row
        elif not (row.last_updated and updated and updated < row.last_updated):
            row.resource = resource
            row.version_id = version
            row.last_updated = updated
        row.sync_job_id = job.id
        row.removed_at = None

    skipped = 0
    for link in data.get("download_links") if isinstance(data.get("download_links"), list) else []:
        url = link.get("url") if isinstance(link, dict) else None
        # Plain http is allowed only for a fake Fasten on this machine; real links are always https.
        local = isinstance(url, str) and url.startswith(("http://localhost", "http://127.0.0.1"))
        if not isinstance(url, str) or not (url.startswith("https://") or local):
            raise EhrError("The export has a download link that is not https.")
        skipped += download_resources(url, keep)
    if seen:
        stamp = now()
        for key, row in existing.items():
            if key not in seen and row.removed_at is None:
                row.removed_at = stamp
    db.flush()
    rebuild_records(db, connection.id)
    job.status = "done"
    job.resource_count = len(seen)
    job.error = f"{skipped} invalid lines skipped" if skipped else None
    job.completed_at = now()
    connection.status = "connected"
    connection.last_synced_at = now()
    chat_server.queue_sync(db, connection.user_id, "ehr")


def handle_event(db: Session, kind: str, connection: EhrConnection | None, job: EhrSyncJob | None, data: dict) -> None:
    if connection is None:
        if kind in EXPORT_EVENTS:
            raise EhrError(f"No connection with org_connection_id {data.get('org_connection_id')!r}.")
        return
    if kind == "patient.ehi_export_success":
        if connection.status == "revoked":
            fail_job(job, "The connection is revoked.")
        else:
            import_export(db, connection, job, data)
    elif kind == "patient.ehi_export_failed":
        if job is not None:
            fail_job(job, str(data.get("failure_reason") or "export_failed"))
        if connection.status != "revoked":
            connection.status = "error"
    elif kind == "patient.authorization_revoked":
        revoke(db, connection, "The health system revoked the connection.")
    elif kind == "patient.connection_success":
        apply_details(connection, data)


def run_webhook(db: Session, payload: dict) -> None:
    event = db.get(WebhookEvent, uuid.UUID(payload["event_id"]))
    if event is None or event.status != "received":
        return
    data = event.payload.get("data") if isinstance(event.payload, dict) else None
    data = data if isinstance(data, dict) else {}
    connection = None
    if data.get("org_connection_id"):
        connection = db.scalar(
            select(EhrConnection).where(EhrConnection.source == "fasten", EhrConnection.org_connection_id == str(data["org_connection_id"]))
        )
    job = sync_job_for(db, connection, data.get("task_id")) if connection is not None and event.event_type in EXPORT_EVENTS else None
    if event.event_type == "patient.ehi_export_success" and connection is not None:
        if job is None:
            job = EhrSyncJob(connection_id=connection.id, external_task_id=str(data["task_id"]) if data.get("task_id") else None)
            db.add(job)
        job.status = "downloading"
        db.commit()
    try:
        with db.begin_nested():
            handle_event(db, event.event_type, connection, job, data)
        event.status = "processed"
    except Exception as exc:
        logger.exception("webhook event %s (%s) failed", event.id, event.event_type)
        event.status = "failed"
        event.error = str(exc)[:2000]
        if job is not None and job.status in IN_PROGRESS:
            fail_job(job, str(exc))
    event.processed_at = now()


def rebuild_records(db: Session, connection_id: uuid.UUID) -> None:
    connection = db.get(EhrConnection, connection_id)
    db.flush()
    owned = select(FhirResource.id).where(FhirResource.connection_id == connection_id)
    for model in RECORD_TABLES:
        db.execute(delete(model).where(model.fhir_resource_id.in_(owned)))
    # The goals come back with new ids, so a journey follows its goal by the FHIR Goal it came from.
    goal_journeys = dict(
        db.execute(
            select(CarePlanGoal.fhir_resource_id, CarePlanGoal.journey_id)
            .join(CarePlan, CarePlan.id == CarePlanGoal.care_plan_id)
            .where(CarePlan.fhir_resource_id.in_(owned), CarePlanGoal.fhir_resource_id.is_not(None), CarePlanGoal.journey_id.is_not(None))
        ).all()
    )
    db.execute(delete(CarePlan).where(CarePlan.fhir_resource_id.in_(owned)))
    live = db.scalars(
        select(FhirResource)
        .where(FhirResource.connection_id == connection_id, FhirResource.removed_at.is_(None))
        .options(undefer(FhirResource.resource))
        .order_by(FhirResource.last_updated.desc().nulls_last(), FhirResource.id)
    ).all()
    by_type: dict[str, list[FhirResource]] = defaultdict(list)
    for row in live:
        by_type[row.resource_type].append(row)

    def mapped(resource_type: str, mapper: Callable):
        for row in by_type[resource_type]:
            try:
                fields = mapper(row.resource)
            except Exception:
                logger.warning("connection %s: could not map %s/%s", connection_id, resource_type, row.fhir_id, exc_info=True)
                continue
            if fields:
                yield row, fields

    def record(model, row: FhirResource, fields: dict):
        item = model(user_id=connection.user_id, fhir_resource_id=row.id, **fields)
        db.add(item)
        return item

    for row, fields in mapped("Condition", fhir_map.condition):
        record(Condition, row, fields)
    for row, fields in mapped("AllergyIntolerance", fhir_map.allergy):
        record(Allergy, row, fields)

    # Newest first, so a repeated code keeps the newest request and a statement never doubles a request.
    medications: dict[tuple, Medication] = {}
    for resource_type in ("MedicationRequest", "MedicationStatement"):
        for row, fields in mapped(resource_type, fhir_map.medication):
            key = (fields["code_system"], fields["code"])
            if fields["code"] is not None and key in medications:
                continue
            medications[key] = record(Medication, row, fields)
    db.flush()
    for row, fields in mapped("MedicationDispense", fhir_map.medication_fill):
        match = medications.get((fields["code_system"], fields["code"])) if fields["code"] is not None else None
        if match is not None:
            record(MedicationFill, row, {**fields, "medication_id": match.id})

    reports: dict[str, LabReport] = {}
    for row, fields in mapped("DiagnosticReport", fhir_map.lab_report):
        result_ids = fields.pop("result_ids")
        report = record(LabReport, row, fields)
        for result_id in result_ids:
            reports[result_id] = report
    db.flush()
    for row, results in mapped("Observation", fhir_map.observations):
        report = reports.get(row.fhir_id)
        for fields in results:
            record(LabResult, row, {**fields, "report_id": report.id if report else None})

    for row, fields in mapped("Encounter", fhir_map.encounter):
        record(Encounter, row, fields)

    by_npi: dict[str, CareTeamMember] = {}
    by_name: dict[str, CareTeamMember] = {}

    def member(row: FhirResource, fields: dict) -> None:
        found = by_npi.get(fields["npi"] or "") or by_name.get(fields["name"].lower())
        if found is None:
            found = record(CareTeamMember, row, fields)
        else:
            for field in ("role", "organization", "npi", "phone"):
                setattr(found, field, getattr(found, field) or fields[field])
        by_name[fields["name"].lower()] = found
        if fields["npi"]:
            by_npi[fields["npi"]] = found

    for row, fields in mapped("Practitioner", fhir_map.practitioner):
        member(row, fields)
    for row, members in mapped("CareTeam", fhir_map.care_team):
        for fields in members:
            member(row, fields)

    goals = {row.fhir_id: {**fields, "fhir_resource_id": row.id} for row, fields in mapped("Goal", fhir_map.goal)}
    for row, fields in mapped("CarePlan", fhir_map.care_plan):
        linked = [goals[goal_id] for goal_id in dict.fromkeys(fields.pop("goal_ids")) if goal_id in goals]
        try:
            plan = care_plans.import_care_plan(
                db, connection.user_id, {**fields, "fhir_resource_id": row.id, "organization": connection.organization, "goals": linked}
            )
        except ValidationError:
            logger.warning("connection %s: could not import CarePlan/%s", connection_id, row.fhir_id, exc_info=True)
            continue
        for goal in plan.goals:
            journey_id = goal_journeys.pop(goal.fhir_resource_id, None)
            if journey_id is not None:
                goal.journey_id = journey_id
                db.get(Journey, journey_id).plan_goal_id = goal.id

    profile = db.get(Profile, connection.user_id)
    for row in by_type["Patient"]:
        reason = fhir_map.patient_mismatch(row.resource, profile.first_name if profile else None, profile.date_of_birth if profile else None)
        if reason:
            logger.warning("connection %s: the patient record does not match the profile: %s", connection_id, reason)
    db.flush()


def resync_due(db: Session) -> int:
    lost = db.scalars(select(EhrSyncJob).where(EhrSyncJob.status == "requested", EhrSyncJob.requested_at < now() - STALE_REQUEST)).all()
    for job in lost:
        fail_job(job, "Fasten sent no export within an hour.")
    stale = db.scalars(
        select(EhrConnection).where(EhrConnection.status == "connected", EhrConnection.last_synced_at < now() - RESYNC_AFTER)
    ).all()
    started = 0
    for connection in stale:
        if job_in_progress(db, connection.id) is None:
            start_sync(db, connection)
            started += 1
    return started
