import base64
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import available_timezones

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, tuple_, update
from sqlalchemy.orm import Session

from app import chat_server, jobs, storage
from app.audit import Audit
from app.auth import DB, Auth, clear_cookie
from app.clock import iso, now
from app.errors import ApiError
from app.idempotency import Idempotent
from app.models import AuthSession, Consent, DataRequest, Profile, UserSettings

router = APIRouter(prefix="/v1/me")

STEPS = ("about_you", "why_rumi", "records", "preferences", "done")
PROFILE_FIELDS = ("first_name", "last_name", "preferred_name", "date_of_birth", "gender", "location", "timezone", "profession", "reason")
SCOPES = ("ai_chat", "ai_patient_facts", "health_records", "everyday_rhythms", "outreach_sms", "outreach_call")
CATEGORIES = ("habit_moments", "insights", "heads_ups", "logistics", "check_ins")
EXPORT_LINK_TTL = 24 * 60 * 60
KNOWN_TIMEZONES = available_timezones()

Tone = Literal["straight_talk", "gentle_nudges"]
ReplyLength = Literal["brief", "balanced", "detailed", "practical"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfilePatch(Strict):
    first_name: str | None = Field(default=None, min_length=1, max_length=200)
    last_name: str | None = Field(default=None, min_length=1, max_length=200)
    preferred_name: str | None = Field(default=None, min_length=1, max_length=200)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, min_length=1, max_length=100)
    location: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = None
    profession: str | None = Field(default=None, min_length=1, max_length=200)
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in KNOWN_TIMEZONES:
            raise ValueError("unknown timezone name")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def in_the_past(cls, value: date | None) -> date | None:
        if value is not None and value >= date.today():
            raise ValueError("must be in the past")
        return value


class OnboardingAnswers(ProfilePatch):
    tone: Tone | None = None
    reply_length: ReplyLength | None = None


class OnboardingPatch(Strict):
    step: Literal["about_you", "why_rumi", "records", "preferences"]
    answers: OnboardingAnswers = OnboardingAnswers()


class PreferencesPatch(Strict):
    tone: Tone | None = None
    reply_length: ReplyLength | None = None
    ai_paused: bool | None = None


class CategoriesPatch(Strict):
    habit_moments: bool | None = None
    insights: bool | None = None
    heads_ups: bool | None = None
    logistics: bool | None = None
    check_ins: bool | None = None


class ChannelsPatch(Strict):
    push: bool | None = None
    sms: bool | None = None
    call: bool | None = None


class NotificationsPatch(Strict):
    categories: CategoriesPatch | None = None
    quiet_start: int | None = Field(default=None, ge=0, le=23)
    quiet_end: int | None = Field(default=None, ge=0, le=23)
    channels: ChannelsPatch | None = None


class ConsentPut(Strict):
    granted: bool
    policy_version: str = Field(min_length=1, max_length=50)


class DeleteBody(Strict):
    confirm: str | None = None


def profile_out(profile: Profile) -> dict:
    out = {field: getattr(profile, field) for field in PROFILE_FIELDS}
    out["date_of_birth"] = profile.date_of_birth.isoformat() if profile.date_of_birth else None
    out["updated_at"] = iso(profile.updated_at)
    return out


def onboarding_out(profile: Profile) -> dict:
    answers = {field: getattr(profile, field) for field in PROFILE_FIELDS if getattr(profile, field) is not None}
    if "date_of_birth" in answers:
        answers["date_of_birth"] = answers["date_of_birth"].isoformat()
    return {"step": profile.onboarding_step, "completed_at": iso(profile.onboarding_completed_at), "answers": answers}


def preferences_out(prefs: UserSettings) -> dict:
    return {"tone": prefs.tone, "reply_length": prefs.reply_length, "ai_paused": prefs.ai_paused}


def notifications_out(prefs: UserSettings) -> dict:
    return {
        "categories": {name: prefs.notification_categories.get(name, True) for name in CATEGORIES},
        "quiet_start": prefs.quiet_start,
        "quiet_end": prefs.quiet_end,
        "channels": {"push": prefs.push_enabled, "sms": prefs.sms_enabled, "call": prefs.call_enabled},
    }


def current_consents(db: Session, user_id: uuid.UUID) -> dict[str, bool]:
    rows = db.scalars(
        select(Consent).where(Consent.user_id == user_id).order_by(Consent.changed_at.desc(), Consent.id.desc())
    )
    current = {scope: False for scope in SCOPES}
    seen: set[str] = set()
    for row in rows:
        if row.scope not in seen:
            seen.add(row.scope)
            current[row.scope] = row.granted
    return current


def apply_profile(profile: Profile, patch: ProfilePatch) -> set[str]:
    changed = set()
    for field in patch.model_fields_set & set(PROFILE_FIELDS):
        if getattr(profile, field) != getattr(patch, field):
            setattr(profile, field, getattr(patch, field))
            changed.add(field)
    return changed


def apply_preferences(prefs: UserSettings, patch: PreferencesPatch | OnboardingAnswers) -> set[str]:
    changed = set()
    for field in ("tone", "reply_length", "ai_paused"):
        value = getattr(patch, field, None)
        if value is not None and getattr(prefs, field) != value:
            setattr(prefs, field, value)
            changed.add(field)
    return changed


@router.get("")
def get_me(auth: Auth, db: DB) -> dict:
    user, _ = auth
    return {
        "profile": profile_out(user.profile),
        "onboarding": onboarding_out(user.profile),
        "preferences": preferences_out(user.settings),
        "notifications": notifications_out(user.settings),
        "consents": current_consents(db, user.id),
    }


@router.get("/profile")
def get_profile(auth: Auth) -> dict:
    return profile_out(auth[0].profile)


@router.patch("/profile")
def patch_profile(patch: ProfilePatch, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    profile = user.profile
    if profile.onboarding_step == "done":
        for field in chat_server.REQUIRED_FIELDS:
            if field in patch.model_fields_set and getattr(patch, field) is None:
                raise ApiError(400, "invalid_request", f"{field} cannot be empty after onboarding.")
    changed = apply_profile(profile, patch)
    if changed & set(chat_server.SYNCED_FIELDS) and profile.onboarding_step == "done":
        chat_server.queue_sync(db, user.id, "profile")
    audit.record("update", "profiles", user.id)
    db.commit()
    return profile_out(profile)


@router.get("/onboarding")
def get_onboarding(auth: Auth) -> dict:
    return onboarding_out(auth[0].profile)


@router.patch("/onboarding")
def patch_onboarding(patch: OnboardingPatch, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    profile = user.profile
    if profile.onboarding_step == "done":
        raise ApiError(400, "invalid_request", "Onboarding is already complete.")
    apply_profile(profile, patch.answers)
    apply_preferences(user.settings, patch.answers)
    # Only POST /onboarding/complete sets "done", so the last step stays at "preferences".
    next_step = STEPS[min(STEPS.index(patch.step) + 1, len(STEPS) - 2)]
    if STEPS.index(next_step) > STEPS.index(profile.onboarding_step):
        profile.onboarding_step = next_step
    audit.record("update", "profiles", user.id)
    db.commit()
    return onboarding_out(profile)


@router.post("/onboarding/complete")
def complete_onboarding(auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    profile = user.profile
    missing = [field for field in chat_server.REQUIRED_FIELDS if getattr(profile, field) in (None, "")]
    if missing:
        raise ApiError(400, "onboarding_incomplete", "Some required fields are empty.", fields=missing)
    if profile.onboarding_step != "done":
        profile.onboarding_step = "done"
        profile.onboarding_completed_at = now()
    synced = chat_server.sync_now(db, user)
    audit.record("update", "profiles", user.id)
    db.commit()
    return {"step": "done", "completed_at": iso(profile.onboarding_completed_at), "chat_synced": synced}


@router.get("/preferences")
def get_preferences(auth: Auth) -> dict:
    return preferences_out(auth[0].settings)


@router.patch("/preferences")
def patch_preferences(patch: PreferencesPatch, auth: Auth, db: DB) -> dict:
    user, _ = auth
    changed = apply_preferences(user.settings, patch)
    if changed & {"tone", "reply_length"} and user.profile.onboarding_step == "done":
        chat_server.queue_sync(db, user.id, "profile")
    db.commit()
    return preferences_out(user.settings)


@router.get("/notifications")
def get_notifications(auth: Auth) -> dict:
    return notifications_out(auth[0].settings)


@router.patch("/notifications")
def patch_notifications(patch: NotificationsPatch, auth: Auth, db: DB) -> dict:
    user, _ = auth
    prefs = user.settings
    if patch.categories is not None:
        prefs.notification_categories = {**prefs.notification_categories, **patch.categories.model_dump(exclude_none=True)}
    if patch.quiet_start is not None:
        prefs.quiet_start = patch.quiet_start
    if patch.quiet_end is not None:
        prefs.quiet_end = patch.quiet_end
    if patch.channels is not None:
        consents = current_consents(db, user.id)
        for channel, scope in (("sms", "outreach_sms"), ("call", "outreach_call")):
            if getattr(patch.channels, channel) and not consents[scope]:
                raise ApiError(409, "consent_required", f"Allow the {scope} consent first.", scope=scope)
        if patch.channels.push is not None:
            prefs.push_enabled = patch.channels.push
        if patch.channels.sms is not None:
            prefs.sms_enabled = patch.channels.sms
        if patch.channels.call is not None:
            prefs.call_enabled = patch.channels.call
    db.commit()
    return notifications_out(prefs)


@router.get("/consents")
def get_consents(auth: Auth, db: DB) -> dict:
    return current_consents(db, auth[0].id)


def encode_cursor(row: Consent) -> str:
    return base64.urlsafe_b64encode(f"{row.changed_at.isoformat()}|{row.id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        changed_at, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(changed_at), uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ApiError(400, "invalid_request", "cursor is not valid.") from exc


@router.get("/consents/history")
def consent_history(
    auth: Auth, db: DB, limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None
) -> dict:
    user, _ = auth
    query = (
        select(Consent)
        .where(Consent.user_id == user.id)
        .order_by(Consent.changed_at.desc(), Consent.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(tuple_(Consent.changed_at, Consent.id) < tuple_(*decode_cursor(cursor)))
    rows = db.scalars(query).all()
    page = rows[:limit]
    return {
        "items": [
            {
                "scope": row.scope,
                "granted": row.granted,
                "policy_version": row.policy_version,
                "platform": row.platform,
                "changed_at": iso(row.changed_at),
            }
            for row in page
        ],
        "next_cursor": encode_cursor(page[-1]) if len(rows) > limit else None,
    }


@router.put("/consents/{scope}")
def put_consent(scope: str, body: ConsentPut, auth: Auth, db: DB, audit: Audit) -> dict:
    if scope not in SCOPES:
        raise ApiError(404, "unknown_scope", f"{scope} is not a consent scope.")
    user, session = auth
    row = Consent(user_id=user.id, scope=scope, granted=body.granted, policy_version=body.policy_version, platform=session.platform)
    db.add(row)
    db.flush()
    audit.record("create", "consents", row.id)
    if not body.granted and scope == "outreach_sms":
        user.settings.sms_enabled = False
    if not body.granted and scope == "outreach_call":
        user.settings.call_enabled = False
    db.commit()
    return {"scope": scope, "granted": row.granted, "changed_at": iso(row.changed_at)}


@router.post("/exports", status_code=202)
def start_export(auth: Auth, db: DB, audit: Audit, idempotency: Idempotent) -> dict:
    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    request = DataRequest(user_id=user.id, kind="export")
    db.add(request)
    db.flush()
    jobs.enqueue(db, "export", {"request_id": str(request.id)})
    out = {"id": str(request.id), "status": "pending"}
    audit.record("export", "data_requests", request.id)
    idempotency.store(202, out)
    db.commit()
    return out


@router.get("/exports/{request_id}")
def export_status(request_id: uuid.UUID, auth: Auth, db: DB) -> dict:
    user, _ = auth
    request = db.get(DataRequest, request_id)
    if request is None or request.user_id != user.id or request.kind != "export":
        raise ApiError(404, "not_found", "No export with that id.")
    out = {"id": str(request.id), "status": request.status}
    if request.status == "ready":
        issued = now()
        out["download_url"] = storage.download_url(request.file_key, EXPORT_LINK_TTL)
        out["expires_at"] = iso(issued + timedelta(seconds=EXPORT_LINK_TTL))
    return out


@router.delete("", status_code=202)
def delete_me(response: Response, auth: Auth, db: DB, audit: Audit, body: DeleteBody | None = None) -> None:
    if body is None or body.confirm != "DELETE":
        raise ApiError(400, "confirmation_required", 'Send {"confirm": "DELETE"} to delete the account.')
    user, session = auth
    db.execute(
        update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now())
    )
    db.add(DataRequest(user_id=user.id, kind="delete"))
    jobs.enqueue(db, "delete_account", {"user_id": str(user.id)})
    audit.record("delete", "users", user.id)
    db.commit()
    if session.platform == "web":
        clear_cookie(response)
