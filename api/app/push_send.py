import json
import time

import httpx
import jwt
from pywebpush import WebPushException, webpush

from app.models import PushDevice
from app.settings import settings

APNS_HOSTS = {"production": "https://api.push.apple.com", "sandbox": "https://api.sandbox.push.apple.com"}
# Apple rejects a token older than an hour and asks for no more than one new token every 20 minutes.
APNS_TOKEN_TTL = 50 * 60

client = httpx.Client(http2=True, timeout=10)
_apns_token: tuple[float, str] | None = None


class SendError(Exception):
    pass


class DeadDevice(Exception):
    pass


def send_web(device: PushDevice, payload: dict) -> None:
    if not settings.vapid_private_key or not settings.vapid_subject:
        raise SendError("VAPID_PRIVATE_KEY or VAPID_SUBJECT is not set")
    subscription = {"endpoint": device.web_endpoint, "keys": {"p256dh": device.web_p256dh, "auth": device.web_auth}}
    try:
        webpush(
            subscription,
            json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=24 * 60 * 60,
            timeout=10,
        )
    except WebPushException as exc:
        if exc.status_code in (404, 410):
            raise DeadDevice(f"web push returned {exc.status_code}") from exc
        raise SendError(f"web push: {exc.message}") from exc


def apns_token() -> str:
    global _apns_token
    if not (settings.apns_key_id and settings.apns_team_id and settings.apns_private_key):
        raise SendError("APNS_KEY_ID, APNS_TEAM_ID, or APNS_PRIVATE_KEY is not set")
    issued = time.time()
    if _apns_token is None or issued - _apns_token[0] > APNS_TOKEN_TTL:
        # The .p8 contents usually arrive through an env var with "\n" in place of line breaks.
        key = settings.apns_private_key.replace("\\n", "\n")
        token = jwt.encode({"iss": settings.apns_team_id, "iat": int(issued)}, key, algorithm="ES256", headers={"kid": settings.apns_key_id})
        _apns_token = (issued, token)
    return _apns_token[1]


def send_apns(device: PushDevice, payload: dict) -> None:
    if not settings.apns_bundle_id:
        raise SendError("APNS_BUNDLE_ID is not set")
    host = APNS_HOSTS["sandbox" if settings.apns_use_sandbox or device.apns_environment == "sandbox" else "production"]
    body = {
        "aps": {"alert": {"title": payload["title"], "body": payload["body"]}, "sound": "default", "thread-id": payload["category"]},
        "id": payload["id"],
        "link": payload["link"],
    }
    headers = {
        "authorization": f"bearer {apns_token()}",
        "apns-topic": settings.apns_bundle_id,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-collapse-id": payload["id"],
    }
    try:
        reply = client.post(f"{host}/3/device/{device.apns_token}", json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise SendError(f"apns: {exc}") from exc
    if reply.status_code == 200:
        return
    if reply.status_code == 410:
        raise DeadDevice("apns returned 410")
    raise SendError(f"apns returned {reply.status_code}: {reply.text[:200]}")
