from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import journeys
from app.auth import DB, Auth
from app.clock import iso, now
from app.me import current_consents
from app.models import Appointment, Log

router = APIRouter(prefix="/v1")

NUMBER_KINDS = ("blood_pressure", "glucose", "weight")
PREP_WINDOW = timedelta(days=7)


@router.get("/today")
def today(auth: Auth, db: DB) -> dict:
    user, _ = auth
    at = now()
    visit = db.scalar(
        select(Appointment)
        .where(Appointment.user_id == user.id, Appointment.status != "cancelled", Appointment.ends_at >= at)
        .options(selectinload(Appointment.prep))
        .order_by(Appointment.starts_at, Appointment.id)
        .limit(1)
    )
    prep_reviewed = bool(visit and visit.prep and visit.prep.reviewed_at)
    latest = []
    for kind in NUMBER_KINDS:
        log = db.scalar(
            select(Log)
            .where(Log.user_id == user.id, Log.kind == kind, Log.deleted_at.is_(None))
            .order_by(Log.taken_at.desc(), Log.id.desc())
            .limit(1)
        )
        if log is not None:
            latest.append({"kind": kind, **log.value, "taken_at": iso(log.taken_at)})
    needs_you = []
    if visit is not None and not prep_reviewed and visit.starts_at <= at + PREP_WINDOW:
        needs_you.append({"kind": "visit_prep", "title": "Get ready for your visit", "link": f"/visits/{visit.id}/prep"})
    if user.profile.onboarding_step != "done":
        needs_you.append({"kind": "onboarding", "title": "Finish setting up", "link": "/onboarding"})
    if not current_consents(db, user.id)["ai_chat"]:
        needs_you.append({"kind": "consent", "title": "Turn on Rumi chat", "link": "/privacy"})
    habits = journeys.today(auth, db)
    return {
        "date": habits["date"],
        "next_visit": {"id": str(visit.id), "starts_at": iso(visit.starts_at), "prep_reviewed": prep_reviewed} if visit else None,
        "latest": latest,
        "habits_due": habits["items"],
        "needs_you": needs_you,
    }
