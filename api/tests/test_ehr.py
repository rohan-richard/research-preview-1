import base64
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from standardwebhooks import Webhook

from app import ehr, jobs, maintenance
from app.clock import now
from app.db import SessionLocal
from app.models import (
    AuditLog,
    CarePlan,
    CarePlanGoal,
    CareTeamMember,
    ChatServerOutbox,
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
    WebhookEvent,
)
from app.settings import settings
from tests.conftest import bearer, sign_in
from tests.test_fhir_map import ALL, CARE_PLAN, CONDITION, GOAL, IMMUNIZATION, PATIENT, RESOLVED_CONDITION, ndjson

UTC = timezone.utc
SECRET = "whsec_" + base64.b64encode(b"rumi-test-webhook-secret-32-byte").decode()
ORG = "fedec7b7-0000-4000-8000-000000000001"
API = "https://api.connect.fastenhealth.com/v1"
FILES = "https://files.fasten.test"
BASIC = "Basic " + base64.b64encode(b"public_test_abc:private_test_xyz").decode()


@pytest.fixture
def fasten(monkeypatch):
    fake = SimpleNamespace(calls=[], org_status="authorized", export_status="pending", task_id="task-1", export_errors=0, files={"export-1.ndjson": ndjson(*ALL)})

    def handler(request: httpx.Request) -> httpx.Response:
        fake.calls.append(request)
        path = request.url.path
        if request.url.host == "files.fasten.test":
            assert "authorization" not in request.headers
            name = path.rsplit("/", 1)[-1]
            if name not in fake.files:
                return httpx.Response(500, text="storage is down")
            return httpx.Response(200, content=fake.files[name], headers={"content-type": "application/fhir+ndjson"})
        if path != "/v1/bridge/catalog":  # the catalog is public
            assert request.headers["authorization"] == BASIC
        if path.startswith("/v1/bridge/org_connection/"):
            data = {
                "org_connection_id": path.rsplit("/", 1)[-1],
                "platform_type": "epic",
                "status": fake.org_status,
                "scope": "patient/*.read",
                "consent_expires_at": "2027-01-01T00:00:00Z",
            }
            if getattr(fake, "brand_id", None):
                data["catalog_brand_id"] = fake.brand_id
            return httpx.Response(200, json={"success": True, "data": data})
        if path == "/v1/bridge/catalog":
            assert request.url.params.get("public_id") == "public_test_abc" and "private" not in str(request.url)
            return httpx.Response(200, json={"success": True, "data": {"id": request.url.params.get("brand_id"), "name": "FooClinic"}})
        if path == "/v1/bridge/fhir/ehi-export" and request.method == "POST":
            if fake.export_errors:
                fake.export_errors -= 1
                return httpx.Response(500, json={"message": "Internal Server Error"})
            return httpx.Response(200, json={"success": True, "data": {"task_id": fake.task_id, "status": fake.export_status}})
        if "/download/" in path:
            return httpx.Response(302, headers={"location": f"{FILES}/{path.rsplit('/', 1)[-1]}?signature=abc"})
        return httpx.Response(404, json={"success": False, "error": "unknown route"})

    monkeypatch.setattr(settings, "fasten_public_id", "public_test_abc")
    monkeypatch.setattr(settings, "fasten_private_key", "private_test_xyz")
    monkeypatch.setattr(settings, "fasten_webhook_secret", SECRET)
    monkeypatch.setattr(ehr, "fasten", httpx.Client(transport=httpx.MockTransport(handler)))
    return fake


@pytest.fixture
def allowed(client, signed_in):
    reply = client.put("/v1/me/consents/health_records", json={"granted": True, "policy_version": "2026-09"}, headers=signed_in.headers)
    assert reply.status_code == 200, reply.text
    return signed_in


def connect(client, headers, org=ORG, **fields):
    body = {"org_connection_id": org, "organization": "Example Health", "platform_type": "epic", **fields}
    reply = client.post("/v1/ehr/connections", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def run_jobs() -> int:
    ran = 0
    with SessionLocal() as db:
        while jobs.run_one(db):
            ran += 1
    return ran


def signed(event_id: str, body: str, secret=SECRET, at: datetime | None = None) -> dict:
    at = at or datetime.now(UTC)
    return {
        "webhook-id": event_id,
        "webhook-timestamp": str(int(at.timestamp())),
        "webhook-signature": Webhook(secret).sign(event_id, at, body),
        "content-type": "application/json",
    }


def deliver(client, kind: str, data: dict, event_id: str | None = None, **sign):
    event_id = event_id or str(uuid.uuid4())
    body = json.dumps({"api_mode": "test", "date": "2026-09-25T09:00:00Z", "id": event_id, "type": kind, "data": data})
    return client.post("/v1/integrations/fasten/webhook", content=body, headers=signed(event_id, body, **sign)), event_id


def export_success(task_id="task-1", files=("export-1.ndjson",), org=ORG) -> dict:
    links = [
        {"url": f"{API}/bridge/fhir/ehi-export/{task_id}/download/{name}", "export_type": "jsonl", "content_type": "application/fhir+ndjson"}
        for name in files
    ]
    return {"org_connection_id": org, "task_id": task_id, "org_id": "org-1", "download_links": links, "stats": {}}


def import_all(client, headers) -> dict:
    connection = connect(client, headers)
    run_jobs()
    reply, _ = deliver(client, "patient.ehi_export_success", export_success())
    assert reply.status_code == 200, reply.text
    run_jobs()
    return connection


def rows(model, **filters):
    with SessionLocal() as db:
        return db.scalars(select(model).where(*(getattr(model, name) == value for name, value in filters.items()))).all()


def load(model, row_id):
    with SessionLocal() as db:
        return db.get(model, uuid.UUID(str(row_id)))


def ids(reply) -> list[str]:
    return [item["id"] for item in reply.json()["items"]]


def test_connecting_needs_the_health_records_consent(client, signed_in, fasten):
    body = {"org_connection_id": ORG, "organization": "Example Health"}
    refused = client.post("/v1/ehr/connections", json=body, headers=signed_in.headers)
    assert refused.status_code == 409 and refused.json()["error"] == {"code": "consent_required", "message": "Allow the health_records consent first.", "scope": "health_records"}
    assert rows(EhrConnection) == [] and fasten.calls == []
    assert client.post("/v1/ehr/connections", json=body).status_code == 401
    assert client.get("/v1/ehr/connections").status_code == 401
    assert client.get("/v1/ehr/summary", headers=signed_in.headers).json() == {
        "connected": False,
        "last_synced_at": None,
        "counts": {"conditions": 0, "allergies": 0, "medications": 0, "lab_types": 0, "encounters": 0, "immunizations": 0, "procedures": 0, "documents": 0},
    }


def test_connecting_saves_the_connection_and_requests_an_export(client, fake_provider, allowed, fasten):
    headers = allowed.headers
    connection = connect(client, headers)
    assert connection == {
        "id": connection["id"],
        "organization": "Example Health",
        "platform_type": "epic",
        "status": "connected",
        "last_synced_at": None,
        "sync": {"status": "requested", "error": None},
    }
    stored = load(EhrConnection, connection["id"])
    assert (stored.source, stored.org_connection_id, stored.scope, stored.user_id) == ("fasten", ORG, "patient/*.read", uuid.UUID(allowed.user["id"]))
    assert stored.consent_expires_at == datetime(2027, 1, 1, tzinfo=UTC) and stored.connected_at is not None
    assert [call.url.path for call in fasten.calls] == [f"/v1/bridge/org_connection/{ORG}"]
    assert client.get("/v1/ehr/connections", headers=headers).json() == {"items": [connection]}
    (queued,) = rows(Job)
    (sync_job,) = rows(EhrSyncJob)
    assert (queued.kind, queued.payload, queued.status) == ("ehr_export", {"sync_job_id": str(sync_job.id)}, "queued")

    assert run_jobs() == 1
    sync_job = load(EhrSyncJob, sync_job.id)
    assert (sync_job.status, sync_job.external_task_id, sync_job.error) == ("requested", "task-1", None)
    export_call = fasten.calls[-1]
    assert (export_call.method, export_call.url.path, json.loads(export_call.content)) == ("POST", "/v1/bridge/fhir/ehi-export", {"org_connection_id": ORG})
    assert load(Job, queued.id).status == "done"

    busy = client.post(f"/v1/ehr/connections/{connection['id']}/sync", headers=headers)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "sync_in_progress"
    again = client.post("/v1/ehr/connections", json={"org_connection_id": ORG, "organization": "Example Health"}, headers=headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_connected"
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com").json())
    client.put("/v1/me/consents/health_records", json={"granted": True, "policy_version": "2026-09"}, headers=other)
    assert client.post("/v1/ehr/connections", json={"org_connection_id": ORG, "organization": "Example Health"}, headers=other).status_code == 409
    assert client.get("/v1/ehr/connections", headers=other).json() == {"items": []}
    assert client.post(f"/v1/ehr/connections/{connection['id']}/sync", headers=other).status_code == 404
    assert client.delete(f"/v1/ehr/connections/{connection['id']}", headers=other).status_code == 404

    keyed = {**headers, "Idempotency-Key": "conn-1"}
    first = client.post("/v1/ehr/connections", json={"org_connection_id": "other-org", "organization": "Other Clinic"}, headers=keyed)
    assert first.status_code == 201 and first.json()["platform_type"] == "epic"
    assert client.post("/v1/ehr/connections", json={"org_connection_id": "other-org", "organization": "Other Clinic"}, headers=keyed).json() == first.json()
    assert len(rows(EhrConnection)) == 2
    assert client.post("/v1/ehr/connections", json={"org_connection_id": "x", "organization": "Y", "extra": 1}, headers=headers).status_code == 400
    assert client.post("/v1/ehr/connections", json={"organization": "Y"}, headers=headers).status_code == 400

    # Fasten answers "success" at once for a sandbox export, and the webhook still follows: the job keeps waiting.
    fasten.export_status = "success"
    assert run_jobs() == 1
    (waiting,) = [job for job in rows(EhrSyncJob) if job.connection_id == uuid.UUID(first.json()["id"])]
    assert (waiting.status, waiting.resource_count, waiting.external_task_id) == ("requested", 0, "task-1")
    reply, _ = deliver(client, "patient.ehi_export_success", export_success(org="other-org"))
    assert reply.status_code == 200 and run_jobs() == 1
    assert load(EhrSyncJob, waiting.id).status == "done"
    # The same finished task again has nothing new: done at once, no webhook needed.
    assert client.post(f"/v1/ehr/connections/{first.json()['id']}/sync", headers=headers).json() == {"sync": {"status": "requested"}}
    assert run_jobs() == 1
    (repeat,) = [job for job in rows(EhrSyncJob) if job.connection_id == uuid.UUID(first.json()["id"]) and job.id != waiting.id]
    assert (repeat.status, repeat.resource_count) == ("done", 0)


def test_a_connection_fasten_cannot_read_is_still_saved(client, allowed, fasten, monkeypatch):
    monkeypatch.setattr(settings, "fasten_private_key", "")
    connection = connect(client, allowed.headers)
    assert connection["status"] == "pending" and connection["sync"]["status"] == "requested"
    run_jobs()
    (job,) = rows(EhrSyncJob)
    assert job.status == "failed" and job.error == "FASTEN_PUBLIC_ID or FASTEN_PRIVATE_KEY is not set"
    listed = client.get("/v1/ehr/connections", headers=allowed.headers).json()["items"][0]
    assert listed["sync"] == {"status": "failed", "error": "FASTEN_PUBLIC_ID or FASTEN_PRIVATE_KEY is not set"}
    assert client.post(f"/v1/ehr/connections/{connection['id']}/sync", headers=allowed.headers).status_code == 202


def test_webhook_checks_the_signature_and_saves_each_event_once(client, allowed, fasten, monkeypatch):
    url = "/v1/integrations/fasten/webhook"

    def body(event_id: str) -> str:
        return json.dumps({"id": event_id, "type": "webhook.test", "data": {"hello": "world"}})

    unsigned = client.post(url, content=body("evt-1"), headers={"content-type": "application/json"})
    assert unsigned.status_code == 401 and unsigned.json()["error"]["code"] == "webhook_signature_invalid"
    (event,) = rows(WebhookEvent)
    assert (event.external_id, event.event_type, event.signature_verified, event.status, event.payload["data"]) == ("evt-1", "webhook.test", False, "failed", {"hello": "world"})
    assert event.error == "The webhook signature is missing or wrong." and rows(Job) == []

    wrong_secret = "whsec_" + base64.b64encode(b"another-secret-for-the-test-xx").decode()
    assert client.post(url, content=body("evt-2"), headers=signed("evt-2", body("evt-2"), secret=wrong_secret)).status_code == 401
    stale = signed("evt-3", body("evt-3"), at=datetime.now(UTC) - timedelta(minutes=10))
    assert client.post(url, content=body("evt-3"), headers=stale).status_code == 401
    tampered = client.post(url, content=body("evt-4").replace("world", "there"), headers=signed("evt-4", body("evt-4")))
    assert tampered.status_code == 401
    assert client.post(url, content="not json", headers=signed("evt-5", "not json")).status_code == 200
    assert len(rows(WebhookEvent)) == 5 and len(rows(Job)) == 1
    assert [row.signature_verified for row in rows(WebhookEvent, event_type="unknown")] == [True]

    # An unsigned request with a real event's id does not stop that event.
    accepted = client.post(url, content=body("evt-1"), headers=signed("evt-1", body("evt-1")))
    assert accepted.status_code == 200 and accepted.content == b""
    assert client.post(url, content=body("evt-1"), headers=signed("evt-1", body("evt-1"))).status_code == 200
    (event,) = rows(WebhookEvent, external_id="evt-1")
    assert (event.signature_verified, event.status, event.error) == (True, "received", None)
    assert len(rows(WebhookEvent)) == 5
    queued = [job for job in rows(Job) if job.payload == {"event_id": str(event.id)}]
    assert len(queued) == 1 and queued[0].kind == "ehr_webhook"
    assert run_jobs() == 2
    event = load(WebhookEvent, event.id)
    assert event.status == "processed" and event.processed_at is not None
    assert all(row.status == "processed" for row in rows(WebhookEvent, signature_verified=True))

    monkeypatch.setattr(settings, "fasten_webhook_secret", "")
    assert client.post(url, content=body("evt-7"), headers=signed("evt-7", body("evt-7"))).status_code == 401
    assert client.post(url, content=body("evt-8"), headers={**signed("evt-8", body("evt-8")), **allowed.headers}).status_code == 401


def test_a_successful_export_imports_the_record(client, allowed, fasten):
    headers = allowed.headers
    connection = import_all(client, headers)
    stored = load(EhrConnection, connection["id"])
    assert stored.status == "connected" and stored.last_synced_at is not None
    (sync_job,) = rows(EhrSyncJob)
    assert (sync_job.status, sync_job.resource_count, sync_job.error) == ("done", len(ALL), None)
    assert sync_job.completed_at is not None
    (event,) = rows(WebhookEvent)
    assert event.status == "processed" and event.error is None
    assert [call.url.host for call in fasten.calls[-2:]] == ["api.connect.fastenhealth.com", "files.fasten.test"]

    raw = {(row.resource_type, row.fhir_id): row for row in rows(FhirResource)}
    assert len(raw) == len(ALL) and all(row.removed_at is None and row.sync_job_id == sync_job.id for row in raw.values())
    condition = raw[("Condition", "cond-1")]
    assert (condition.version_id, condition.last_updated, condition.user_id) == ("3", datetime(2026, 9, 20, 12, 0, tzinfo=UTC), uuid.UUID(allowed.user["id"]))
    with SessionLocal() as db:
        assert db.get(FhirResource, condition.id).resource == CONDITION
    assert ("Immunization", "imm-1") in raw

    assert len(rows(Condition)) == 2 and len(rows(Encounter)) == 2 and len(rows(LabReport)) == 1
    assert sorted(row.code for row in rows(Medication)) == ["197361", "861007"]
    (metformin,) = rows(Medication, code="861007")
    assert len(rows(MedicationFill, medication_id=metformin.id)) == 2 and len(rows(MedicationFill)) == 2
    results = rows(LabResult)
    assert sorted(row.code for row in results) == ["20453-7", "4548-4", "4548-4", "8462-4", "8480-6"]
    (report,) = rows(LabReport)
    with_report = {row.fhir_resource_id: row.report_id for row in results if row.report_id}
    assert with_report == {raw[("Observation", "obs-a1c-2")].id: report.id}
    assert sorted(row.name for row in rows(CareTeamMember)) == ["Dr. Anita Patel", "Sam Lee, RN"]

    (outbox,) = rows(ChatServerOutbox)
    assert (outbox.kind, outbox.payload, outbox.status) == ("sync", {"sections": ["ehr"]}, "pending")
    assert client.get("/v1/ehr/summary", headers=headers).json() == {
        "connected": True,
        "last_synced_at": connection_synced(client, headers),
        "counts": {"conditions": 2, "allergies": 1, "medications": 2, "lab_types": 4, "encounters": 2, "immunizations": 1, "procedures": 1, "documents": 1},
    }
    listed = client.get("/v1/ehr/connections", headers=headers).json()["items"][0]
    assert listed["status"] == "connected" and listed["sync"] == {"status": "done", "error": None} and listed["last_synced_at"].endswith("Z")


def connection_synced(client, headers) -> str:
    return client.get("/v1/ehr/connections", headers=headers).json()["items"][0]["last_synced_at"]


def test_the_record_routes_show_what_was_imported(client, fake_provider, allowed, fasten):
    headers = allowed.headers
    connection = import_all(client, headers)
    source = {"connection_id": connection["id"], "organization": "Example Health", "fhir_type": "Condition", "last_updated": "2026-09-20T12:00:00Z"}

    active = client.get("/v1/ehr/conditions", headers=headers).json()
    assert active["next_cursor"] is None and active["items"] == [
        {
            "id": active["items"][0]["id"],
            "code": {"system": "http://snomed.info/sct", "code": "44054006", "display": "Type 2 diabetes mellitus"},
            "clinical_status": "active",
            "onset_date": "2021-04-02",
            "abatement_date": None,
            "source": source,
        }
    ]
    resolved = client.get("/v1/ehr/conditions?status=resolved", headers=headers).json()["items"]
    assert [(item["code"]["display"], item["onset_date"], item["abatement_date"]) for item in resolved] == [("Asthma", "2010-05-01", "2018-06-30")]
    assert resolved[0]["source"]["last_updated"] == "2026-09-19T08:00:00Z"
    everything = client.get("/v1/ehr/conditions?status=all", headers=headers).json()["items"]
    assert [item["code"]["display"] for item in everything] == ["Asthma", "Type 2 diabetes mellitus"]
    page = client.get("/v1/ehr/conditions?status=all&limit=1", headers=headers).json()
    assert [item["code"]["display"] for item in page["items"]] == ["Asthma"] and page["next_cursor"]
    rest = client.get(f"/v1/ehr/conditions?status=all&limit=1&cursor={page['next_cursor']}", headers=headers).json()
    assert [item["code"]["display"] for item in rest["items"]] == ["Type 2 diabetes mellitus"] and rest["next_cursor"] is None
    assert client.get("/v1/ehr/conditions?cursor=garbage", headers=headers).status_code == 400
    assert client.get("/v1/ehr/conditions?status=gone", headers=headers).status_code == 400

    (allergy,) = client.get("/v1/ehr/allergies", headers=headers).json()["items"]
    assert allergy == {
        "id": allergy["id"],
        "code": {"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "7980", "display": "Penicillin"},
        "criticality": "high",
        "reaction": "Hives",
        "clinical_status": "active",
        "source": {**source, "fhir_type": "AllergyIntolerance"},
    }

    (metformin,) = client.get("/v1/ehr/medications", headers=headers).json()["items"]
    assert metformin == {
        "id": metformin["id"],
        "code": {"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "861007", "display": "Metformin 500 MG Oral Tablet"},
        "status": "active",
        "dose_text": "Take 1 tablet twice a day with meals",
        "start_date": "2021-04-10",
        "end_date": None,
        "prescriber": "Dr. A. Patel",
        "next_refill_date": "2026-10-04",
        "source": {**source, "fhir_type": "MedicationRequest"},
    }
    (amlodipine,) = client.get("/v1/ehr/medications?status=stopped", headers=headers).json()["items"]
    assert (amlodipine["code"]["display"], amlodipine["status"], amlodipine["end_date"], amlodipine["next_refill_date"]) == ("Amlodipine 5 MG Oral Tablet", "stopped", "2024-02-01", None)
    assert amlodipine["source"]["fhir_type"] == "MedicationStatement"
    assert len(client.get("/v1/ehr/medications?status=all", headers=headers).json()["items"]) == 2
    detail = client.get(f"/v1/ehr/medications/{metformin['id']}", headers=headers).json()
    assert detail == {
        **metformin,
        "quantity": 60.0,
        "refills_allowed": 3,
        "days_supply": 30,
        "fills": [
            {"dispensed_at": "2026-09-04T14:10:00Z", "quantity": 60.0, "days_supply": 30, "pharmacy": "Example Pharmacy", "expected_refill_date": "2026-10-04"},
            {"dispensed_at": "2026-08-05T15:00:00Z", "quantity": 60.0, "days_supply": 30, "pharmacy": "Example Pharmacy", "expected_refill_date": "2026-09-04"},
        ],
    }
    assert client.get(f"/v1/ehr/medications/{uuid.uuid4()}", headers=headers).status_code == 404

    labs = client.get("/v1/ehr/labs", headers=headers).json()
    assert [(item["code"]["code"], item["category"], item["count"]) for item in labs["items"]] == [
        ("8462-4", "vital-signs", 1),
        ("20453-7", "laboratory", 1),
        ("4548-4", "laboratory", 2),
        ("8480-6", "vital-signs", 1),
    ]
    assert labs["items"][2] == {
        "code": {"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"},
        "category": "laboratory",
        "latest": {"value": 7.1, "unit": "%", "interpretation": "high", "effective_at": "2026-09-16T08:30:00Z"},
        "count": 2,
    }
    assert labs["items"][1]["latest"]["value"] == "Negative"
    page = client.get("/v1/ehr/labs?limit=3", headers=headers).json()
    rest = client.get(f"/v1/ehr/labs?limit=3&cursor={page['next_cursor']}", headers=headers).json()
    assert [item["code"]["code"] for item in rest["items"]] == ["8480-6"] and rest["next_cursor"] is None

    series = client.get("/v1/ehr/labs/4548-4", headers=headers).json()
    assert series == {
        "code": {"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"},
        "category": "laboratory",
        "unit": "%",
        "range_low": 4.0,
        "range_high": 5.6,
        "points": [{"value": 7.4, "effective_at": "2026-03-10T08:30:00Z"}, {"value": 7.1, "effective_at": "2026-09-16T08:30:00Z"}],
    }
    assert client.get("/v1/ehr/labs/4548-4?from=2026-06-01", headers=headers).json()["points"] == [{"value": 7.1, "effective_at": "2026-09-16T08:30:00Z"}]
    assert client.get("/v1/ehr/labs/4548-4?from=2026-01-01&to=2026-03-31", headers=headers).json()["points"] == [{"value": 7.4, "effective_at": "2026-03-10T08:30:00Z"}]
    assert client.get("/v1/ehr/labs/4548-4?from=yesterday", headers=headers).status_code == 400
    assert client.get("/v1/ehr/labs/0000-0", headers=headers).status_code == 404

    encounters = client.get("/v1/ehr/encounters", headers=headers).json()["items"]
    assert [(item["class"], item["start_at"], item["reason"]) for item in encounters] == [
        ("ambulatory", "2026-09-16T14:00:00Z", "Diabetes follow-up"),
        ("virtual", "2026-03-10T09:00:00Z", "Annual review"),
    ]
    assert encounters[0] == {
        "id": encounters[0]["id"],
        "class": "ambulatory",
        "type": "Office visit",
        "start_at": "2026-09-16T14:00:00Z",
        "end_at": "2026-09-16T14:30:00Z",
        "practitioner": "Dr. A. Patel",
        "organization": "Example Health",
        "reason": "Diabetes follow-up",
        "source": {**source, "fhir_type": "Encounter"},
    }
    page = client.get("/v1/ehr/encounters?limit=1", headers=headers).json()
    assert ids(client.get(f"/v1/ehr/encounters?limit=1&cursor={page['next_cursor']}", headers=headers)) == [encounters[1]["id"]]

    team = client.get("/v1/ehr/care-team", headers=headers).json()["items"]
    assert team == [
        {
            "id": team[0]["id"],
            "name": "Dr. Anita Patel",
            "role": "Primary care",
            "organization": "Example Health",
            "npi": "1234567890",
            "phone": "+1 555 010 0000",
            "source": {**source, "fhir_type": "Practitioner"},
        },
        {
            "id": team[1]["id"],
            "name": "Sam Lee, RN",
            "role": "Diabetes educator",
            "organization": "Example Health",
            "npi": None,
            "phone": None,
            "source": {**source, "fhir_type": "CareTeam"},
        },
    ]

    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com").json())
    for path in ("conditions", "allergies", "medications", "labs", "encounters", "care-team"):
        assert client.get(f"/v1/ehr/{path}", headers=other).json() == {"items": [], "next_cursor": None}
        assert client.get(f"/v1/ehr/{path}").status_code == 401
    assert client.get(f"/v1/ehr/medications/{metformin['id']}", headers=other).status_code == 404
    assert client.get("/v1/ehr/labs/4548-4", headers=other).status_code == 404
    reads = sorted(row.resource for row in rows(AuditLog, action="read"))
    assert reads == sorted(["conditions"] * 6 + ["allergies"] * 2 + ["medications"] * 4 + ["lab_results"] * 4 + ["encounters"] * 4 + ["care_team_members"] * 2)


def test_patient_details_come_from_the_newest_patient_resource(client, fake_provider, allowed, fasten):
    headers = allowed.headers
    missing = client.get("/v1/ehr/patient", headers=headers)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"

    import_all(client, headers)
    assert client.get("/v1/ehr/patient", headers=headers).json() == {
        "first_name": "Elena",
        "last_name": "Ruiz",
        "preferred_name": None,
        "date_of_birth": "1971-03-14",
        "gender": "female",
        "location": None,
        "phone": None,
    }
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com").json())
    assert client.get("/v1/ehr/patient", headers=other).status_code == 404
    assert client.get("/v1/ehr/patient").status_code == 401
    assert [row.resource for row in rows(AuditLog, action="read")] == ["fhir_resources"]


def test_immunizations_procedures_and_documents_come_from_the_raw_resources(client, fake_provider, allowed, fasten):
    headers = allowed.headers
    newer = {**IMMUNIZATION, "id": "imm-2", "occurrenceDateTime": "2026-09-01T10:00:00Z", "vaccineCode": {"text": "COVID-19"}}
    undated = {**IMMUNIZATION, "id": "imm-3", "occurrenceDateTime": None}
    fasten.files["export-1.ndjson"] = ndjson(*ALL, newer, undated)
    connection = import_all(client, headers)
    source = {"connection_id": connection["id"], "organization": "Example Health", "last_updated": "2026-09-20T12:00:00Z"}

    shots = client.get("/v1/ehr/immunizations", headers=headers).json()
    assert [(item["display"], item["occurred_at"]) for item in shots["items"]] == [
        ("COVID-19", "2026-09-01T10:00:00Z"),
        ("Influenza, seasonal", "2025-10-02T00:00:00Z"),
        ("Influenza, seasonal", None),
    ]
    assert shots["next_cursor"] is None
    raw = {(row.resource_type, row.fhir_id): row for row in rows(FhirResource)}
    assert shots["items"][1] == {
        "id": str(raw[("Immunization", "imm-1")].id),
        "display": "Influenza, seasonal",
        "occurred_at": "2025-10-02T00:00:00Z",
        "status": "completed",
        "source": {**source, "fhir_type": "Immunization"},
    }
    page = client.get("/v1/ehr/immunizations?limit=2", headers=headers).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = client.get(f"/v1/ehr/immunizations?limit=2&cursor={page['next_cursor']}", headers=headers)
    assert ids(rest) == [shots["items"][2]["id"]] and rest.json()["next_cursor"] is None
    assert client.get("/v1/ehr/immunizations?cursor=garbage", headers=headers).status_code == 400

    assert client.get("/v1/ehr/procedures", headers=headers).json()["items"] == [
        {
            "id": str(raw[("Procedure", "proc-1")].id),
            "display": "Colonoscopy",
            "performed_at": "2024-06-11T09:00:00Z",
            "status": "completed",
            "source": {**source, "fhir_type": "Procedure"},
        }
    ]
    assert client.get("/v1/ehr/documents", headers=headers).json()["items"] == [
        {
            "id": str(raw[("DocumentReference", "doc-1")].id),
            "title": "Visit summary",
            "date": "2026-09-12T15:30:00Z",
            "type": "Progress note",
            "content_type": "application/pdf",
            "has_attachment": True,
            "source": {**source, "fhir_type": "DocumentReference"},
        }
    ]

    # A resource that a later export no longer has leaves the list and the count.
    with SessionLocal() as db:
        db.get(FhirResource, raw[("Immunization", "imm-2")].id).removed_at = now()
        db.commit()
    assert len(client.get("/v1/ehr/immunizations", headers=headers).json()["items"]) == 2
    assert client.get("/v1/ehr/summary", headers=headers).json()["counts"]["immunizations"] == 2

    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com").json())
    for path in ("immunizations", "procedures", "documents"):
        assert client.get(f"/v1/ehr/{path}", headers=other).json() == {"items": [], "next_cursor": None}
        assert client.get(f"/v1/ehr/{path}").status_code == 401
    reads = sorted(row.resource for row in rows(AuditLog, action="read"))
    assert reads == sorted(["immunizations"] * 5 + ["procedures"] * 2 + ["documents"] * 2)


def test_a_later_export_replaces_and_removes_resources(client, allowed, fasten):
    headers = allowed.headers
    connection = import_all(client, headers)
    renamed = {**CONDITION, "meta": {"versionId": "4", "lastUpdated": "2026-09-26T12:00:00Z"}, "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Diabetes mellitus type 2"}]}}
    older = {**PATIENT, "meta": {"versionId": "0", "lastUpdated": "2026-01-01T00:00:00Z"}, "name": [{"family": "Old", "given": ["Name"]}]}
    second = [renamed if item is CONDITION else older if item is PATIENT else item for item in ALL if item is not RESOLVED_CONDITION]
    fasten.files["export-2.ndjson"] = ndjson(*second)
    fasten.task_id = "task-2"

    assert client.post(f"/v1/ehr/connections/{connection['id']}/sync", headers=headers).status_code == 202
    run_jobs()
    reply, _ = deliver(client, "patient.ehi_export_success", export_success("task-2", ("export-2.ndjson",)))
    assert reply.status_code == 200
    run_jobs()

    raw = {(row.resource_type, row.fhir_id): row for row in rows(FhirResource)}
    assert len(raw) == len(ALL)
    assert raw[("Condition", "cond-2")].removed_at is not None
    assert raw[("Condition", "cond-1")].version_id == "4" and raw[("Condition", "cond-1")].removed_at is None
    assert raw[("Patient", "pat-1")].version_id == "1"
    with SessionLocal() as db:
        assert db.get(FhirResource, raw[("Patient", "pat-1")].id).resource == PATIENT
    done = sorted(rows(EhrSyncJob), key=lambda job: job.requested_at)
    assert [(job.status, job.resource_count, job.external_task_id) for job in done] == [("done", len(ALL), "task-1"), ("done", len(ALL) - 1, "task-2")]
    assert all(row.sync_job_id == done[1].id for key, row in raw.items() if key != ("Condition", "cond-2"))
    everything = client.get("/v1/ehr/conditions?status=all", headers=headers).json()["items"]
    assert [item["code"]["display"] for item in everything] == ["Diabetes mellitus type 2"]
    assert everything[0]["source"]["last_updated"] == "2026-09-26T12:00:00Z"
    assert client.get("/v1/ehr/summary", headers=headers).json()["counts"]["conditions"] == 1

    # A third export brings the condition back.
    fasten.files["export-3.ndjson"] = ndjson(*ALL)
    fasten.task_id = "task-3"
    client.post(f"/v1/ehr/connections/{connection['id']}/sync", headers=headers)
    run_jobs()
    deliver(client, "patient.ehi_export_success", export_success("task-3", ("export-3.ndjson",)))
    run_jobs()
    assert load(FhirResource, raw[("Condition", "cond-2")].id).removed_at is None
    assert client.get("/v1/ehr/summary", headers=headers).json()["counts"]["conditions"] == 2


def export_again(client, headers, fasten, connection_id: str, task_id: str, *resources) -> None:
    fasten.files[f"{task_id}.ndjson"] = ndjson(*resources)
    fasten.task_id = task_id
    assert client.post(f"/v1/ehr/connections/{connection_id}/sync", headers=headers).status_code == 202
    run_jobs()
    reply, _ = deliver(client, "patient.ehi_export_success", export_success(task_id, (f"{task_id}.ndjson",)))
    assert reply.status_code == 200
    run_jobs()


def test_care_plans_come_from_the_export_and_a_later_export_replaces_them(client, allowed, fasten):
    headers = allowed.headers
    fasten.files["export-1.ndjson"] = ndjson(*ALL, CARE_PLAN, GOAL)
    connection = import_all(client, headers)

    listed = client.get("/v1/care-plans", headers=headers).json()["items"]
    assert listed == [
        {
            "id": listed[0]["id"],
            "title": "Diabetes self management plan",
            "description": "Keep A1c and blood pressure in range.",
            "status": "active",
            "period_start": "2026-04-01",
            "period_end": None,
            "author": "Dr. A. Patel",
            "goal_count": 1,
            "source": {"organization": "Example Health", "fhir_type": "CarePlan"},
        }
    ]
    plan = client.get(f"/v1/care-plans/{listed[0]['id']}", headers=headers).json()
    goal = plan["goals"][0]
    assert goal == {
        "id": goal["id"],
        "description": "Keep A1c below 7%",
        "target": {"code": "4548-4", "value": 7.0, "unit": "%"},
        "due_date": "2027-03-31",
        "status": "active",
        "journey_id": None,
    }
    assert [(item["kind"], item["description"], item["status"], item["scheduled_for"]) for item in plan["activities"]] == [
        ("lab", "A1c test every 3 months", "scheduled", "2026-12-15"),
        ("education", "Diabetes nutrition class", "not_started", None),
        ("medication", "Metformin 500 MG", "in_progress", None),
        ("appointment", "Follow-up visit", "not_started", None),
    ]
    raw = {(row.resource_type, row.fhir_id): row.id for row in rows(FhirResource)}
    assert rows(CarePlan)[0].fhir_resource_id == raw[("CarePlan", "cp-1")]
    assert rows(CarePlanGoal)[0].fhir_resource_id == raw[("Goal", "goal-1")]
    started = client.post(f"/v1/care-plans/{plan['id']}/goals/{goal['id']}/journey", headers=headers)
    assert started.status_code == 201, started.text
    journey = started.json()

    # The second export replaces the plan. The journey moves to the goal from the same FHIR Goal.
    renamed = {**CARE_PLAN, "title": "Diabetes plan, updated", "status": "completed"}
    export_again(client, headers, fasten, connection["id"], "task-2", *ALL, renamed, {**GOAL, "description": {"text": "Keep A1c below 6.5%"}})
    assert client.get("/v1/care-plans", headers=headers).json()["items"] == []
    listed = client.get("/v1/care-plans?status=all", headers=headers).json()["items"]
    assert [item["title"] for item in listed] == ["Diabetes plan, updated"] and listed[0]["status"] == "completed"
    assert len(rows(CarePlan)) == 1 and len(rows(CarePlanGoal)) == 1
    goal = client.get(f"/v1/care-plans/{listed[0]['id']}", headers=headers).json()["goals"][0]
    assert goal["description"] == "Keep A1c below 6.5%" and goal["journey_id"] == journey["id"]
    assert load(Journey, journey["id"]).plan_goal_id == uuid.UUID(goal["id"])

    # Without the Goal, the plan has no goals and the journey stays with no goal.
    export_again(client, headers, fasten, connection["id"], "task-3", *ALL, renamed)
    assert client.get("/v1/care-plans?status=all", headers=headers).json()["items"][0]["goal_count"] == 0
    assert len(rows(CarePlan)) == 1 and rows(CarePlanGoal) == []
    assert load(Journey, journey["id"]).plan_goal_id is None
    assert client.get(f"/v1/journeys/{journey['id']}", headers=headers).status_code == 200

    assert client.delete(f"/v1/ehr/connections/{connection['id']}?delete_data=true", headers=headers).status_code == 204
    assert rows(CarePlan) == [] and client.get("/v1/care-plans?status=all", headers=headers).json()["items"] == []


def test_bad_lines_are_counted_and_a_download_failure_fails_the_job(client, allowed, fasten, caplog):
    headers = allowed.headers
    stranger = {**PATIENT, "name": [{"family": "Doe", "given": ["John"]}], "birthDate": "1980-01-01"}
    fasten.files["export-1.ndjson"] = ndjson(stranger, CONDITION) + b"\n\n{not json}\n" + json.dumps({"resourceType": "Condition"}).encode() + b"\n" + ndjson(RESOLVED_CONDITION)
    # The alembic upgrade in conftest loads alembic.ini logging, which disables every logger that exists at that point.
    logging.getLogger("app.ehr").disabled = False
    with caplog.at_level(logging.WARNING, logger="app.ehr"):
        connection = import_all(client, headers)
    (job,) = rows(EhrSyncJob)
    assert (job.status, job.resource_count, job.error) == ("done", 3, "2 invalid lines skipped")
    assert len(rows(Condition)) == 2
    assert "patient record does not match the profile" in caplog.text and "given name john is not Elena" in caplog.text

    fasten.task_id = "task-2"
    client.post(f"/v1/ehr/connections/{connection['id']}/sync", headers=headers)
    run_jobs()
    reply, event_id = deliver(client, "patient.ehi_export_success", export_success("task-2", ("missing.ndjson",)))
    assert reply.status_code == 200
    run_jobs()
    (event,) = rows(WebhookEvent, external_id=event_id)
    assert event.status == "failed" and event.error == "download returned 500"
    failed = [job for job in rows(EhrSyncJob) if job.external_task_id == "task-2"]
    assert len(failed) == 1 and failed[0].status == "failed" and failed[0].error == "download returned 500"
    assert len(rows(Condition)) == 2 and load(EhrConnection, connection["id"]).status == "connected"
    assert client.post(f"/v1/ehr/connections/{connection['id']}/sync", headers=headers).status_code == 202

    unknown, event_id = deliver(client, "patient.ehi_export_success", export_success(org="nobody"))
    assert unknown.status_code == 200
    run_jobs()
    (event,) = rows(WebhookEvent, external_id=event_id)
    assert event.status == "failed" and event.error == "No connection with org_connection_id 'nobody'."


def test_failed_and_revoked_events_move_the_connection(client, allowed, fasten):
    headers = allowed.headers
    connection = connect(client, headers)
    run_jobs()
    reply, _ = deliver(client, "patient.ehi_export_failed", {"org_connection_id": ORG, "task_id": "task-1", "org_id": "org-1", "failure_reason": "token_refresh_failure"})
    assert reply.status_code == 200
    run_jobs()
    (job,) = rows(EhrSyncJob)
    assert (job.status, job.error) == ("failed", "token_refresh_failure") and job.completed_at is not None
    listed = client.get("/v1/ehr/connections", headers=headers).json()["items"][0]
    assert listed["status"] == "error" and listed["sync"] == {"status": "failed", "error": "token_refresh_failure"}

    assert client.post(f"/v1/ehr/connections/{connection['id']}/sync", headers=headers).status_code == 202
    run_jobs()
    reply, _ = deliver(client, "patient.connection_success", {"org_connection_id": ORG, "connection_status": "authorized", "scope": "patient/Observation.read", "consent_expires_at": "2027-06-01T00:00:00Z", "platform_type": "epic"})
    run_jobs()
    stored = load(EhrConnection, connection["id"])
    assert (stored.status, stored.scope, stored.consent_expires_at) == ("connected", "patient/Observation.read", datetime(2027, 6, 1, tzinfo=UTC))

    reply, _ = deliver(client, "patient.authorization_revoked", {"org_connection_id": ORG, "connection_status": "revoked"})
    assert reply.status_code == 200
    run_jobs()
    stored = load(EhrConnection, connection["id"])
    assert stored.status == "revoked" and stored.revoked_at is not None
    assert [job.status for job in rows(EhrSyncJob)] == ["failed", "failed"]
    refused = client.post(f"/v1/ehr/connections/{connection['id']}/sync", headers=headers)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "connection_revoked"
    assert client.get("/v1/ehr/summary", headers=headers).json()["connected"] is False

    # A late success for a revoked connection imports nothing.
    deliver(client, "patient.ehi_export_success", export_success("task-9"))
    run_jobs()
    assert rows(FhirResource) == [] and [job.status for job in rows(EhrSyncJob)] == ["failed", "failed", "failed"]

    # Connecting the same system again reuses the row.
    again = connect(client, headers)
    assert again["id"] == connection["id"] and again["status"] == "connected" and again["sync"]["status"] == "requested"
    assert load(EhrConnection, connection["id"]).revoked_at is None
    assert all(event.status == "processed" for event in rows(WebhookEvent))


def test_disconnecting_keeps_or_deletes_the_records(client, allowed, fasten):
    headers = allowed.headers
    connection = import_all(client, headers)
    url = f"/v1/ehr/connections/{connection['id']}"
    assert client.delete(url, headers=headers).status_code == 204
    stored = load(EhrConnection, connection["id"])
    assert stored.status == "revoked" and stored.revoked_at is not None
    assert len(rows(FhirResource)) == len(ALL) and len(rows(Condition)) == 2
    summary = client.get("/v1/ehr/summary", headers=headers).json()
    assert summary["connected"] is False and summary["counts"]["conditions"] == 2 and summary["last_synced_at"]
    assert client.get("/v1/ehr/connections", headers=headers).json()["items"][0]["status"] == "revoked"
    assert client.get("/v1/ehr/conditions?status=all", headers=headers).json()["items"][1]["source"]["connection_id"] == connection["id"]
    assert client.delete(url, headers=headers).status_code == 204

    assert client.delete(f"{url}?delete_data=true", headers=headers).status_code == 204
    assert rows(FhirResource) == [] and rows(Condition) == [] and rows(LabResult) == [] and rows(MedicationFill) == [] and rows(CareTeamMember) == []
    assert client.get("/v1/ehr/summary", headers=headers).json()["counts"] == {
        "conditions": 0,
        "allergies": 0,
        "medications": 0,
        "lab_types": 0,
        "encounters": 0,
        "immunizations": 0,
        "procedures": 0,
        "documents": 0,
    }
    assert client.get("/v1/ehr/labs", headers=headers).json()["items"] == []
    assert len(rows(EhrSyncJob)) == 1 and load(EhrConnection, connection["id"]) is not None
    assert client.delete(f"/v1/ehr/connections/{uuid.uuid4()}", headers=headers).status_code == 404
    deletes = [row for row in rows(AuditLog, action="delete") if row.resource == "ehr_connections"]
    assert len(deletes) == 3


def test_the_daily_resync_picks_only_stale_connections(client, allowed, fasten):
    headers = allowed.headers
    connection = import_all(client, headers)
    with SessionLocal() as db:
        assert ehr.resync_due(db) == 0
        stored = db.get(EhrConnection, uuid.UUID(connection["id"]))
        stored.last_synced_at = now() - timedelta(hours=25)
        db.commit()
        assert ehr.resync_due(db) == 1
        db.commit()
        assert ehr.resync_due(db) == 0
    requested = [job for job in rows(EhrSyncJob) if job.status == "requested"]
    assert len(requested) == 1 and len([job for job in rows(Job) if job.status == "queued"]) == 1
    assert client.get("/v1/ehr/connections", headers=headers).json()["items"][0]["sync"]["status"] == "requested"
    assert run_jobs() == 1 and load(EhrSyncJob, requested[0].id).external_task_id == "task-1"

    fasten.task_id = "task-2"
    deliver(client, "patient.ehi_export_success", export_success("task-1"))
    run_jobs()
    assert load(EhrConnection, connection["id"]).last_synced_at > now() - timedelta(minutes=1)
    with SessionLocal() as db:
        stored = db.get(EhrConnection, uuid.UUID(connection["id"]))
        stored.last_synced_at = now() - timedelta(hours=25)
        stored.status = "revoked"
        db.commit()
        assert ehr.resync_due(db) == 0
        stored.status = "error"
        db.commit()
        assert ehr.resync_due(db) == 0
        stored.status = "connected"
        db.commit()
        maintenance.run(db)
    assert len([job for job in rows(EhrSyncJob) if job.status == "requested"]) == 1


def test_the_stitch_page_serves_the_widget_without_secrets(client, monkeypatch):
    # The same page lands Fasten's hosted connect flow: the connection id arrives in the query string.
    assert client.get("/v1/integrations/fasten/stitch").status_code == 404
    monkeypatch.setattr(settings, "fasten_public_id", "public_test_abc")
    monkeypatch.setattr(settings, "fasten_private_key", "private_test_xyz")
    reply = client.get("/v1/integrations/fasten/stitch")
    assert reply.status_code == 200 and reply.headers["content-type"].startswith("text/html")
    assert reply.headers["cache-control"] == "no-store"
    assert '<fasten-stitch-element public-id="public_test_abc">' in reply.text
    assert "private_test_xyz" not in reply.text and "window.webkit.messageHandlers.fasten" in reply.text
    assert "cdn.fastenhealth.com/connect/v4/fasten-stitch-element.js" in reply.text
    (nonce,) = re.findall(r'<script nonce="([^"]+)">', reply.text)
    policy = reply.headers["content-security-policy"]
    assert f"script-src https://cdn.fastenhealth.com 'nonce-{nonce}'" in policy and "default-src 'none'" in policy
    assert re.findall(r'<script nonce="([^"]+)">', client.get("/v1/integrations/fasten/stitch").text) != [nonce]


def test_the_organization_name_comes_from_the_catalog(client, allowed, fasten):
    fasten.brand_id = "brand-1"
    connection = connect(client, allowed.headers, org="brand-org", organization="Epic health system")
    assert connection["organization"] == "FooClinic"
    assert [call.url.path for call in fasten.calls] == ["/v1/bridge/org_connection/brand-org", "/v1/bridge/catalog"]
    assert fasten.calls[-1].url.params.get("api_mode") == "test"


def test_lost_export_requests_fail_after_an_hour(client, allowed, fasten):
    connection = connect(client, allowed.headers)
    run_jobs()
    (job,) = rows(EhrSyncJob)
    with SessionLocal() as db:
        stuck = db.get(EhrSyncJob, job.id)
        stuck.requested_at = datetime.now(UTC) - timedelta(hours=2)
        db.commit()
        assert ehr.resync_due(db) == 0
        db.commit()
    assert load(EhrSyncJob, job.id).status == "failed"
    listed = client.get("/v1/ehr/connections", headers=allowed.headers).json()["items"][0]
    assert listed["id"] == connection["id"] and listed["sync"]["status"] == "failed"


def test_a_fasten_server_error_is_retried(client, allowed, fasten):
    connect(client, allowed.headers)
    fasten.export_errors = 1
    assert run_jobs() == 1
    (sync_job,) = rows(EhrSyncJob)
    (queued,) = rows(Job)
    assert load(EhrSyncJob, sync_job.id).status == "requested"
    assert (queued.status, queued.attempts) == ("queued", 1) and "500" in queued.last_error

    with SessionLocal() as db:
        db.get(Job, queued.id).run_at = datetime.now(UTC)
        db.commit()
    assert run_jobs() == 1
    assert load(Job, queued.id).status == "done"
    assert (load(EhrSyncJob, sync_job.id).status, load(EhrSyncJob, sync_job.id).external_task_id) == ("requested", "task-1")


def test_the_sync_fails_when_fasten_keeps_failing(client, allowed, fasten):
    connect(client, allowed.headers)
    fasten.export_errors = 99
    (queued,) = rows(Job)
    for _ in range(jobs.MAX_ATTEMPTS):
        with SessionLocal() as db:
            db.get(Job, queued.id).run_at = datetime.now(UTC)
            db.commit()
        run_jobs()
    assert load(Job, queued.id).status == "failed"
    (sync_job,) = rows(EhrSyncJob)
    assert sync_job.status == "failed" and "returned 500" in sync_job.error
