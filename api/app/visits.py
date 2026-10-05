import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select, tuple_
from sqlalchemy.orm import Session, selectinload

from app.audit import Audit
from app.auth import DB, Auth
from app.clock import iso, now
from app.errors import ApiError
from app.idempotency import Idempotent
from app.logs import decode_cursor, encode_cursor
from app.models import Appointment, GuideItem, Log, VisitPrep, VisitPrepLog

router = APIRouter(prefix="/v1")

APPOINTMENT_FIELDS = ("clinician", "organization", "location", "kind", "status", "starts_at", "ends_at", "join_link", "reason")
REQUIRED_FIELDS = ("kind", "status", "starts_at", "ends_at")
PREP_FIELDS = ("step", "goal", "changes", "medication_concerns", "questions", "practical_needs")

AppointmentKind = Literal["in_person", "video"]
AppointmentStatus = Literal["pending", "confirmed", "cancelled", "done"]
Step = Literal["focus", "changes", "questions", "review"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppointmentPatch(Strict):
    clinician: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=500)
    kind: AppointmentKind | None = None
    status: AppointmentStatus | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    join_link: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("join_link")
    @classmethod
    def http_link(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value


class AppointmentPost(AppointmentPatch):
    kind: AppointmentKind
    status: AppointmentStatus = "confirmed"
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class PrepPut(Strict):
    # Accepted so a client can send the GET body back. The path names the appointment.
    appointment_id: uuid.UUID | None = None
    step: Step = "focus"
    goal: str = Field(default="", max_length=2000)
    changes: str = Field(default="", max_length=2000)
    medication_concerns: str = Field(default="", max_length=2000)
    questions: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(default_factory=list, max_length=50)
    practical_needs: str = Field(default="", max_length=2000)
    log_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class GuideItemPost(Strict):
    kind: Literal["question", "observation"]
    text: str = Field(min_length=1, max_length=1000)
    added_from: str | None = Field(default=None, max_length=200)
    appointment_id: uuid.UUID | None = None


class GuideItemPatch(Strict):
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    appointment_id: uuid.UUID | None = None
    resolved: bool | None = None


def appointment_out(appointment: Appointment) -> dict:
    prep = appointment.prep
    return {
        "id": str(appointment.id),
        "clinician": appointment.clinician,
        "organization": appointment.organization,
        "location": appointment.location,
        "kind": appointment.kind,
        "status": appointment.status,
        "starts_at": iso(appointment.starts_at),
        "ends_at": iso(appointment.ends_at),
        "join_link": appointment.join_link,
        "reason": appointment.reason,
        "instructions": appointment.instructions,
        "source": appointment.source,
        "prep": {"step": prep.step if prep else "focus", "reviewed": bool(prep and prep.reviewed_at)},
    }


def prep_log_ids(db: Session, prep: VisitPrep) -> list[str]:
    query = (
        select(VisitPrepLog.log_id)
        .join(Log)
        .where(VisitPrepLog.appointment_id == prep.appointment_id, Log.deleted_at.is_(None))
        .order_by(Log.taken_at, Log.id)
    )
    return [str(log_id) for log_id in db.scalars(query)]


def prep_out(db: Session, prep: VisitPrep) -> dict:
    out = {"appointment_id": str(prep.appointment_id)}
    out.update({field: getattr(prep, field) for field in PREP_FIELDS})
    out["log_ids"] = prep_log_ids(db, prep)
    out["reviewed_at"] = iso(prep.reviewed_at)
    out["updated_at"] = iso(prep.updated_at)
    return out


def guide_item_out(item: GuideItem) -> dict:
    return {
        "id": str(item.id),
        "kind": item.kind,
        "text": item.text,
        "added_from": item.added_from,
        "appointment_id": str(item.appointment_id) if item.appointment_id else None,
        "resolved": item.resolved,
    }


def load_appointment(db: Session, user_id: uuid.UUID, appointment_id: uuid.UUID) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None or appointment.user_id != user_id:
        raise ApiError(404, "not_found", "No appointment with that id.")
    return appointment


def load_prep(db: Session, user_id: uuid.UUID, appointment_id: uuid.UUID, for_write: bool = False) -> VisitPrep:
    appointment = load_appointment(db, user_id, appointment_id)
    if for_write and appointment.status == "cancelled":
        raise ApiError(404, "not_found", "The appointment is cancelled.")
    if appointment.prep is None:
        appointment.prep = VisitPrep(user_id=user_id)
        db.flush()
    return appointment.prep


def clear_review(prep: VisitPrep | None) -> None:
    if prep is not None:
        prep.reviewed_at = None
        prep.reviewed_text = None


def apply_appointment(appointment: Appointment, patch: AppointmentPatch) -> set[str]:
    changed = set()
    for field in patch.model_fields_set & set(APPOINTMENT_FIELDS):
        value = getattr(patch, field)
        if value is None and field in REQUIRED_FIELDS:
            raise ApiError(400, "invalid_request", f"{field} cannot be empty.")
        if getattr(appointment, field) != value:
            setattr(appointment, field, value)
            changed.add(field)
    if appointment.ends_at <= appointment.starts_at:
        raise ApiError(400, "invalid_request", "ends_at must be after starts_at.")
    return changed


def set_prep_logs(db: Session, user_id: uuid.UUID, prep: VisitPrep, log_ids: list[uuid.UUID]) -> None:
    wanted = set(log_ids)
    if wanted:
        found = set(db.scalars(select(Log.id).where(Log.user_id == user_id, Log.id.in_(wanted), Log.deleted_at.is_(None))))
        if wanted - found:
            raise ApiError(400, "invalid_request", "log_ids: no log with that id.")
    db.execute(delete(VisitPrepLog).where(VisitPrepLog.appointment_id == prep.appointment_id))
    db.add_all(VisitPrepLog(appointment_id=prep.appointment_id, log_id=log_id) for log_id in wanted)


def review_text(db: Session, prep: VisitPrep) -> str:
    lines = [
        f"Goal: {prep.goal}",
        f"Changes since last visit: {prep.changes}",
        f"Medication concerns: {prep.medication_concerns}",
        "Questions:",
        *(f"- {question}" for question in prep.questions),
        f"Practical needs: {prep.practical_needs}",
        "Logs to bring:",
    ]
    logs = db.scalars(
        select(Log)
        .join(VisitPrepLog)
        .where(VisitPrepLog.appointment_id == prep.appointment_id, Log.deleted_at.is_(None))
        .order_by(Log.taken_at, Log.id)
    )
    for log in logs:
        values = ", ".join(f"{name} {value}" for name, value in log.value.items())
        lines.append(f"- {log.kind.replace('_', ' ')} on {iso(log.taken_at)}: {values}")
    return "\n".join(lines)


@router.get("/appointments")
def list_appointments(
    auth: Auth,
    db: DB,
    audit: Audit,
    status: Literal["upcoming", "past", "all"] = "upcoming",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> dict:
    user, _ = auth
    query = select(Appointment).where(Appointment.user_id == user.id).options(selectinload(Appointment.prep)).limit(limit + 1)
    if status == "upcoming":
        query = query.where(Appointment.ends_at >= now()).order_by(Appointment.starts_at, Appointment.id)
        if cursor:
            query = query.where(tuple_(Appointment.starts_at, Appointment.id) > tuple_(*decode_cursor(cursor)))
    else:
        if status == "past":
            query = query.where(Appointment.ends_at < now())
        query = query.order_by(Appointment.starts_at.desc(), Appointment.id.desc())
        if cursor:
            query = query.where(tuple_(Appointment.starts_at, Appointment.id) < tuple_(*decode_cursor(cursor)))
    rows = db.scalars(query).all()
    audit.record("read", "appointments")
    db.commit()
    page = rows[:limit]
    return {
        "items": [appointment_out(row) for row in page],
        "next_cursor": encode_cursor(page[-1].starts_at, page[-1].id) if len(rows) > limit else None,
    }


@router.post("/appointments", status_code=201)
def add_appointment(body: AppointmentPost, auth: Auth, db: DB, audit: Audit, idempotency: Idempotent) -> dict:
    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    appointment = Appointment(user_id=user.id, source="patient", prep=VisitPrep(user_id=user.id))
    apply_appointment(appointment, body)
    db.add(appointment)
    db.flush()
    out = appointment_out(appointment)
    audit.record("create", "appointments", appointment.id)
    idempotency.store(201, out)
    db.commit()
    return out


@router.get("/appointments/{appointment_id}")
def get_appointment(appointment_id: uuid.UUID, auth: Auth, db: DB) -> dict:
    return appointment_out(load_appointment(db, auth[0].id, appointment_id))


@router.patch("/appointments/{appointment_id}")
def patch_appointment(appointment_id: uuid.UUID, body: AppointmentPatch, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    appointment = load_appointment(db, user.id, appointment_id)
    if appointment.source != "patient":
        raise ApiError(403, "read_only", "Appointments from the clinic change only through a new sync.")
    changed = apply_appointment(appointment, body)
    if changed & {"starts_at", "ends_at"}:
        clear_review(appointment.prep)
    audit.record("update", "appointments", appointment.id)
    db.commit()
    return appointment_out(appointment)


@router.delete("/appointments/{appointment_id}", status_code=204)
def delete_appointment(appointment_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> None:
    user, _ = auth
    appointment = load_appointment(db, user.id, appointment_id)
    if appointment.source != "patient":
        raise ApiError(403, "read_only", "Appointments from the clinic change only through a new sync.")
    db.delete(appointment)
    audit.record("delete", "appointments", appointment.id)
    db.commit()


@router.get("/appointments/{appointment_id}/prep")
def get_prep(appointment_id: uuid.UUID, auth: Auth, db: DB) -> dict:
    prep = load_prep(db, auth[0].id, appointment_id)
    db.commit()
    return prep_out(db, prep)


@router.put("/appointments/{appointment_id}/prep")
def put_prep(
    appointment_id: uuid.UUID, body: PrepPut, auth: Auth, db: DB, audit: Audit, if_match: Annotated[str | None, Header()] = None
) -> dict:
    user, _ = auth
    prep = load_prep(db, user.id, appointment_id, for_write=True)
    if if_match is not None and if_match.strip('"') != iso(prep.updated_at):
        raise ApiError(409, "edit_conflict", "The prep changed on another device.", prep=prep_out(db, prep))
    for field in PREP_FIELDS:
        setattr(prep, field, getattr(body, field))
    set_prep_logs(db, user.id, prep, body.log_ids)
    clear_review(prep)
    prep.updated_at = now()
    audit.record("update", "visit_preps", prep.appointment_id)
    db.commit()
    return prep_out(db, prep)


@router.post("/appointments/{appointment_id}/prep/review")
def review_prep(appointment_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> dict:
    prep = load_prep(db, auth[0].id, appointment_id, for_write=True)
    prep.reviewed_at = now()
    prep.reviewed_text = review_text(db, prep)
    audit.record("update", "visit_preps", prep.appointment_id)
    db.commit()
    return {"reviewed_at": iso(prep.reviewed_at), "reviewed_text": prep.reviewed_text}


@router.get("/guide-items")
def list_guide_items(
    auth: Auth,
    db: DB,
    resolved: Literal["false", "true", "all"] = "false",
    appointment_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> dict:
    user, _ = auth
    query = (
        select(GuideItem)
        .where(GuideItem.user_id == user.id)
        .order_by(GuideItem.created_at.desc(), GuideItem.id.desc())
        .limit(limit + 1)
    )
    if resolved != "all":
        query = query.where(GuideItem.resolved.is_(resolved == "true"))
    if appointment_id:
        query = query.where(GuideItem.appointment_id == appointment_id)
    if cursor:
        query = query.where(tuple_(GuideItem.created_at, GuideItem.id) < tuple_(*decode_cursor(cursor)))
    rows = db.scalars(query).all()
    page = rows[:limit]
    return {
        "items": [guide_item_out(row) for row in page],
        "next_cursor": encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None,
    }


@router.post("/guide-items", status_code=201)
def add_guide_item(body: GuideItemPost, auth: Auth, db: DB, audit: Audit, idempotency: Idempotent) -> dict:
    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    if body.appointment_id:
        load_appointment(db, user.id, body.appointment_id)
    item = GuideItem(user_id=user.id, **body.model_dump())
    db.add(item)
    db.flush()
    out = guide_item_out(item)
    audit.record("create", "guide_items", item.id)
    idempotency.store(201, out)
    db.commit()
    return out


@router.patch("/guide-items/{item_id}")
def patch_guide_item(item_id: uuid.UUID, body: GuideItemPatch, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    item = db.get(GuideItem, item_id)
    if item is None or item.user_id != user.id:
        raise ApiError(404, "not_found", "No guide item with that id.")
    if body.text is not None:
        item.text = body.text
    if "appointment_id" in body.model_fields_set:
        if body.appointment_id:
            load_appointment(db, user.id, body.appointment_id)
        item.appointment_id = body.appointment_id
    if body.resolved is not None:
        item.resolved = body.resolved
    audit.record("update", "guide_items", item.id)
    db.commit()
    return guide_item_out(item)


@router.delete("/guide-items/{item_id}", status_code=204)
def delete_guide_item(item_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> None:
    user, _ = auth
    item = db.get(GuideItem, item_id)
    if item is None or item.user_id != user.id:
        raise ApiError(404, "not_found", "No guide item with that id.")
    db.delete(item)
    audit.record("delete", "guide_items", item.id)
    db.commit()
