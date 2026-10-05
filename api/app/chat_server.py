import logging
import uuid
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import age_on, now
from app.models import ChatServerOutbox, Profile, User
from app.settings import settings

logger = logging.getLogger(__name__)

# /onboardPerson refuses a call that misses any of these.
REQUIRED_FIELDS = ("first_name", "date_of_birth", "gender", "location", "timezone", "profession", "reason")
SYNCED_FIELDS = REQUIRED_FIELDS + ("preferred_name",)

# The chat server answers slowly while any chat turn runs its LLM calls on its event loop.
client = httpx.Client(timeout=45)


class ChatServerError(Exception):
    pass


def questionnaire(profile: Profile, today: date | None = None) -> dict:
    missing = [field for field in REQUIRED_FIELDS if getattr(profile, field) in (None, "")]
    if missing:
        raise ChatServerError(f"profile is missing {', '.join(missing)}")
    return {
        "name": profile.preferred_name or profile.first_name,
        "age": age_on(profile.date_of_birth, today or date.today()),
        "gender": profile.gender,
        "location": profile.location,
        "profession": profile.profession,
        "reason": profile.reason,
        "timezone": profile.timezone,
    }


def _url(path: str) -> str:
    if not settings.chat_server_url:
        raise ChatServerError("CHAT_SERVER_URL is not set")
    return settings.chat_server_url.rstrip("/") + path


def onboard_person(external_ref: str, answers: dict, api_key: str | None = None) -> None:
    body = {"api_key": api_key or settings.chat_server_api_key, "external_ref": external_ref, "onboarding_questionnaire": answers}
    try:
        reply = client.post(_url("/onboardPerson"), json=body)
    except httpx.HTTPError as exc:
        raise ChatServerError(f"onboardPerson: {exc}") from exc
    if reply.status_code != 200:
        raise ChatServerError(f"onboardPerson returned {reply.status_code}: {reply.text[:200]}")


def generate_token(api_key: str, user_ref: str) -> str:
    try:
        reply = client.post(_url("/generateToken"), json={"api_key": api_key, "user_ref": user_ref})
    except httpx.HTTPError as exc:
        raise ChatServerError(f"generateToken: {exc}") from exc
    if reply.status_code != 200:
        raise ChatServerError(f"generateToken returned {reply.status_code}: {reply.text[:200]}")
    token = reply.json().get("access_token") if reply.headers.get("content-type", "").startswith("application/json") else None
    if not token:
        raise ChatServerError("generateToken returned no access_token")
    return token


def delete_person(external_ref: str) -> None:
    try:
        reply = client.post(_url("/deletePerson"), json={"api_key": settings.chat_server_api_key, "external_ref": external_ref})
    except httpx.HTTPError as exc:
        raise ChatServerError(f"deletePerson: {exc}") from exc
    # 404 means the chat server holds nothing for this person, which is the outcome we want.
    if reply.status_code not in (200, 404):
        raise ChatServerError(f"deletePerson returned {reply.status_code}: {reply.text[:200]}")


def sync_user(db: Session, user_id: uuid.UUID) -> None:
    profile = db.get(Profile, user_id)
    if profile is None or profile.onboarding_step != "done":
        return
    onboard_person(str(user_id), questionnaire(profile))
    profile.chat_synced_at = now()


def sync_now(db: Session, user: User) -> bool:
    try:
        sync_user(db, user.id)
        return True
    except ChatServerError as exc:
        logger.warning("chat sync for %s deferred: %s", user.id, exc)
        queue_sync(db, user.id, "profile")
        return False


def queue_sync(db: Session, user_id: uuid.UUID, section: str) -> None:
    pending = db.scalar(
        select(ChatServerOutbox)
        .where(ChatServerOutbox.user_id == user_id, ChatServerOutbox.kind == "sync", ChatServerOutbox.status == "pending")
        .with_for_update()
    )
    if pending is None:
        db.add(ChatServerOutbox(user_id=user_id, kind="sync", payload={"sections": [section]}))
    elif section not in pending.payload.get("sections", []):
        pending.payload = {**pending.payload, "sections": [*pending.payload.get("sections", []), section]}


def queue_delete(db: Session, user_id: uuid.UUID) -> None:
    db.add(ChatServerOutbox(user_id=user_id, kind="delete", payload={}))
