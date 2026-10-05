import hmac
import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app import notifications
from app.audit import Audit
from app.auth import DB, Auth
from app.clock import iso, now
from app.errors import ApiError
from app.idempotency import Idempotent
from app.logs import decode_cursor, encode_cursor
from app.models import Notification, PushDevice, User
from app.settings import settings

router = APIRouter(prefix="/v1")

HEX = re.compile(r"[0-9a-fA-F]+")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WebKeys(Strict):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class WebSubscription(Strict):
    endpoint: str = Field(min_length=1, max_length=2000)
    keys: WebKeys


class DevicePost(Strict):
    platform: Literal["web", "ios"]
    name: str | None = Field(default=None, max_length=200)
    subscription: WebSubscription | None = None
    apns_token: str | None = Field(default=None, min_length=1, max_length=400)
    environment: Literal["production", "sandbox"] | None = None


class NudgePost(Strict):
    tenant_id: str = Field(max_length=200)
    person_id: uuid.UUID
    content: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


def device_out(device: PushDevice) -> dict:
    return {
        "id": str(device.id),
        "platform": device.platform,
        "name": device.name,
        "enabled": device.enabled,
        "created_at": iso(device.created_at),
    }


def notification_out(row: Notification) -> dict:
    return {
        "id": str(row.id),
        "category": row.category,
        "body": row.body,
        "link": row.link,
        "status": row.status,
        "skip_reason": row.skip_reason,
        "sent_at": iso(row.sent_at),
        "opened_at": iso(row.opened_at),
    }


def load_device(db: Session, user_id: uuid.UUID, device_id: uuid.UUID) -> PushDevice:
    device = db.get(PushDevice, device_id)
    if device is None or device.user_id != user_id:
        raise ApiError(404, "not_found", "No device with that id.")
    return device


@router.get("/push/web-key")
def web_key(auth: Auth) -> dict:
    if not settings.vapid_public_key:
        raise ApiError(503, "push_not_configured", "Web push is not configured on this server.")
    return {"vapid_public_key": settings.vapid_public_key}


@router.post("/push/devices", status_code=201)
def register_device(body: DevicePost, auth: Auth, db: DB, audit: Audit, idempotency: Idempotent) -> dict:
    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    if body.platform == "web":
        if body.subscription is None or not body.subscription.endpoint.startswith("https://"):
            raise ApiError(400, "invalid_subscription", "Send a Web Push subscription with an https endpoint and keys.")
        device = db.scalar(select(PushDevice).where(PushDevice.web_endpoint == body.subscription.endpoint))
        fields = {
            "web_endpoint": body.subscription.endpoint,
            "web_p256dh": body.subscription.keys.p256dh,
            "web_auth": body.subscription.keys.auth,
            "apns_token": None,
            "apns_environment": None,
        }
    else:
        if not body.apns_token or not HEX.fullmatch(body.apns_token) or body.environment is None:
            raise ApiError(400, "invalid_subscription", "Send a hex apns_token and the environment for an iOS device.")
        device = db.scalar(select(PushDevice).where(PushDevice.apns_token == body.apns_token).limit(1))
        fields = {
            "apns_token": body.apns_token,
            "apns_environment": body.environment,
            "web_endpoint": None,
            "web_p256dh": None,
            "web_auth": None,
        }
    new = device is None
    if new:
        device = PushDevice(platform=body.platform)
        db.add(device)
    # A known token or endpoint moves to whoever is signed in on that device now.
    device.user_id = user.id
    device.name = body.name
    device.enabled = True
    device.failure_count = 0
    for field, value in fields.items():
        setattr(device, field, value)
    db.flush()
    out = device_out(device)
    audit.record("create" if new else "update", "push_devices", device.id)
    idempotency.store(201, out)
    db.commit()
    return out


@router.get("/push/devices")
def list_devices(auth: Auth, db: DB) -> dict:
    user, _ = auth
    rows = db.scalars(select(PushDevice).where(PushDevice.user_id == user.id).order_by(PushDevice.created_at, PushDevice.id))
    return {"items": [device_out(row) | {"last_sent_at": iso(row.last_sent_at)} for row in rows]}


@router.delete("/push/devices/{device_id}", status_code=204)
def delete_device(device_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> None:
    user, _ = auth
    device = load_device(db, user.id, device_id)
    db.delete(device)
    audit.record("delete", "push_devices", device.id)
    db.commit()


@router.post("/push/devices/{device_id}/test", status_code=202)
def send_test(device_id: uuid.UUID, auth: Auth, db: DB) -> dict:
    user, _ = auth
    device = load_device(db, user.id, device_id)
    if not device.enabled:
        raise ApiError(409, "device_disabled", "This device is turned off. Register it again.")
    payload = {"id": str(uuid.uuid4()), "title": notifications.TITLE, "body": "Notifications are on", "link": "/today", "category": "logistics"}
    error = notifications.push_to_device(device, payload, now())
    db.commit()
    return {"sent": error is None, "error": error}


@router.get("/notifications")
def list_notifications(auth: Auth, db: DB, limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None) -> dict:
    user, _ = auth
    query = (
        select(Notification)
        .where(Notification.user_id == user.id, Notification.status != "scheduled")
        .order_by(Notification.scheduled_for.desc(), Notification.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(tuple_(Notification.scheduled_for, Notification.id) < tuple_(*decode_cursor(cursor)))
    rows = db.scalars(query).all()
    page = rows[:limit]
    return {
        "items": [notification_out(row) for row in page],
        "next_cursor": encode_cursor(page[-1].scheduled_for, page[-1].id) if len(rows) > limit else None,
    }


@router.post("/notifications/{notification_id}/opened", status_code=204)
def mark_opened(notification_id: uuid.UUID, auth: Auth, db: DB) -> None:
    user, _ = auth
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "No notification with that id.")
    if row.opened_at is None:
        row.opened_at = now()
    db.commit()


@router.post("/integrations/chat-server/nudge", status_code=202)
def chat_server_nudge(body: NudgePost, db: DB, x_rumi_webhook_secret: Annotated[str | None, Header()] = None) -> dict:
    expected = settings.chat_server_webhook_secret
    if not expected or x_rumi_webhook_secret is None or not hmac.compare_digest(x_rumi_webhook_secret, expected):
        raise ApiError(401, "webhook_secret_invalid", "The webhook secret is missing or wrong.")
    if db.get(User, body.person_id) is None:
        raise ApiError(404, "not_found", "No user with that id.")
    row = notifications.add_nudge(db, body.person_id, body.content, f"chat_nudge:{body.idempotency_key}")
    db.commit()
    return {"id": str(row.id)}
