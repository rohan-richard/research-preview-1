import base64
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Select, select, tuple_, update
from sqlalchemy.orm import Session

from app.audit import Audit
from app.auth import DB, Auth
from app.clock import iso, now
from app.errors import ApiError
from app.idempotency import Idempotent
from app.models import Log, VisitPrep, VisitPrepLog

router = APIRouter(prefix="/v1/logs")

DAY = timedelta(hours=24)
UNITS = {"blood_pressure": "mmHg", "glucose": "mg/dL", "weight": "kg"}

Kind = Literal["blood_pressure", "glucose", "weight", "symptom", "medication_taken", "meal", "activity", "note"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BloodPressure(Strict):
    systolic: int = Field(ge=50, le=300)
    diastolic: int = Field(ge=30, le=200)
    pulse: int | None = Field(default=None, ge=20, le=300)


class Glucose(Strict):
    mg_dl: int = Field(ge=10, le=1000)
    timing: Literal["fasting", "before_meal", "after_meal", "bedtime"]


class Weight(Strict):
    kg: float = Field(gt=0, le=500)


class Symptom(Strict):
    name: str = Field(min_length=1, max_length=200)
    severity: int = Field(ge=1, le=10)
    body_region: str | None = Field(default=None, max_length=100)


class MedicationTaken(Strict):
    medication_id: uuid.UUID
    status: Literal["taken", "skipped", "late"]


class Meal(Strict):
    description: str = Field(min_length=1, max_length=1000)
    library_item: str | None = Field(default=None, max_length=200)


class Activity(Strict):
    description: str = Field(min_length=1, max_length=1000)
    minutes: int | None = Field(default=None, ge=1, le=1440)


class Note(Strict):
    text: str = Field(min_length=1, max_length=5000)


SHAPES = {
    "blood_pressure": BloodPressure,
    "glucose": Glucose,
    "weight": Weight,
    "symptom": Symptom,
    "medication_taken": MedicationTaken,
    "meal": Meal,
    "activity": Activity,
    "note": Note,
}
HINTS = {
    "blood_pressure": "Enter a pair such as 138/84.",
    "glucose": "Enter a whole number in mg/dL and when you took it.",
    "weight": "Enter a weight in kg.",
    "symptom": "Enter a name and a severity from 1 to 10.",
    "medication_taken": "Enter the medication and whether you took it.",
    "meal": "Enter what you ate.",
    "activity": "Enter what you did.",
    "note": "Enter some text.",
}


class LogPost(Strict):
    kind: Kind
    value: dict
    taken_at: AwareDatetime
    note: str | None = Field(default=None, max_length=2000)


class LogPatch(Strict):
    value: dict | None = None
    taken_at: AwareDatetime | None = None
    note: str | None = Field(default=None, max_length=2000)


def check_value(kind: str, value: dict) -> dict:
    try:
        return SHAPES[kind].model_validate(value).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        where = ".".join(["value", *(str(part) for part in exc.errors()[0]["loc"])])
        raise ApiError(400, "invalid_value", HINTS[kind], field=where) from exc


def medication_id(kind: str, value: dict) -> uuid.UUID | None:
    return uuid.UUID(value["medication_id"]) if kind == "medication_taken" else None


def log_out(log: Log) -> dict:
    return {
        "id": str(log.id),
        "kind": log.kind,
        "value": log.value,
        "taken_at": iso(log.taken_at),
        "note": log.note,
        "source": log.source,
        "created_at": iso(log.created_at),
    }


def load_log(db: Session, user_id: uuid.UUID, log_id: uuid.UUID, include_deleted: bool = False) -> Log:
    log = db.get(Log, log_id)
    if log is None or log.user_id != user_id or (log.deleted_at is not None and not include_deleted):
        raise ApiError(404, "not_found", "No log with that id.")
    return log


def clear_prep_reviews(db: Session, log_id: uuid.UUID) -> None:
    using = select(VisitPrepLog.appointment_id).where(VisitPrepLog.log_id == log_id)
    db.execute(
        update(VisitPrep)
        .where(VisitPrep.appointment_id.in_(using), VisitPrep.reviewed_at.is_not(None))
        .values(reviewed_at=None, reviewed_text=None)
    )


def day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def in_range(query: Select, kind: str | None, start: date | None, end: date | None) -> Select:
    if kind:
        query = query.where(Log.kind == kind)
    if start:
        query = query.where(Log.taken_at >= day_start(start))
    if end:
        query = query.where(Log.taken_at < day_start(end) + timedelta(days=1))
    return query


def encode_cursor(stamp: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{stamp.isoformat()}|{row_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        stamp, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(stamp), uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ApiError(400, "invalid_request", "cursor is not valid.") from exc


@router.post("", status_code=201)
def add_log(body: LogPost, auth: Auth, db: DB, audit: Audit, idempotency: Idempotent) -> dict:
    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    value = check_value(body.kind, body.value)
    log = Log(
        user_id=user.id, kind=body.kind, value=value, taken_at=body.taken_at, note=body.note, medication_id=medication_id(body.kind, value)
    )
    db.add(log)
    db.flush()
    out = log_out(log)
    audit.record("create", "logs", log.id)
    idempotency.store(201, out)
    db.commit()
    return out


@router.get("")
def list_logs(
    auth: Auth,
    db: DB,
    audit: Audit,
    kind: Kind | None = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> dict:
    user, _ = auth
    query = (
        select(Log)
        .where(Log.user_id == user.id, Log.deleted_at.is_(None))
        .order_by(Log.taken_at.desc(), Log.id.desc())
        .limit(limit + 1)
    )
    query = in_range(query, kind, start, to)
    if cursor:
        query = query.where(tuple_(Log.taken_at, Log.id) < tuple_(*decode_cursor(cursor)))
    rows = db.scalars(query).all()
    audit.record("read", "logs")
    db.commit()
    page = rows[:limit]
    return {
        "items": [log_out(row) for row in page],
        "next_cursor": encode_cursor(page[-1].taken_at, page[-1].id) if len(rows) > limit else None,
    }


@router.get("/series")
def series(
    auth: Auth,
    db: DB,
    kind: Literal["blood_pressure", "glucose", "weight"],
    start: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> dict:
    user, _ = auth
    query = select(Log).where(Log.user_id == user.id, Log.deleted_at.is_(None)).order_by(Log.taken_at, Log.id)
    rows = db.scalars(in_range(query, kind, start, to))
    return {
        "kind": kind,
        "unit": UNITS[kind],
        "points": [{"taken_at": iso(row.taken_at), **row.value, "source": row.source} for row in rows],
    }


@router.get("/{log_id}")
def get_log(log_id: uuid.UUID, auth: Auth, db: DB) -> dict:
    return log_out(load_log(db, auth[0].id, log_id))


@router.patch("/{log_id}")
def patch_log(log_id: uuid.UUID, body: LogPatch, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    log = load_log(db, user.id, log_id)
    if body.value is not None:
        log.value = check_value(log.kind, body.value)
        log.medication_id = medication_id(log.kind, log.value)
    if body.taken_at is not None:
        log.taken_at = body.taken_at
    if "note" in body.model_fields_set:
        log.note = body.note
    clear_prep_reviews(db, log.id)
    audit.record("update", "logs", log.id)
    db.commit()
    return log_out(log)


@router.delete("/{log_id}", status_code=204)
def delete_log(log_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> None:
    user, _ = auth
    log = load_log(db, user.id, log_id)
    log.deleted_at = now()
    clear_prep_reviews(db, log.id)
    audit.record("delete", "logs", log.id)
    db.commit()


@router.post("/{log_id}/restore")
def restore_log(log_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    log = load_log(db, user.id, log_id, include_deleted=True)
    if log.deleted_at is not None:
        if log.deleted_at < now() - DAY:
            raise ApiError(410, "restore_expired", "This log was deleted more than 24 hours ago.")
        log.deleted_at = None
        clear_prep_reviews(db, log.id)
        audit.record("update", "logs", log.id)
        db.commit()
    return log_out(log)
