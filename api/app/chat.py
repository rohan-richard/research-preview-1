from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter

from app import chat_server
from app.auth import DB, Auth
from app.errors import ApiError
from app.me import current_consents
from app.settings import settings

router = APIRouter(prefix="/v1/chat")

TOKEN_TTL = 600
TENANTS = {"chat": "rumi-chat", "visit_prep": "rumi-visit-prep"}


def socket_url() -> str:
    parts = urlsplit(settings.chat_server_url.rstrip("/") + "/ws")
    return urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc, parts.path, "", ""))


@router.get("/token")
def chat_token(auth: Auth, db: DB, purpose: Literal["chat", "visit_prep"] = "chat") -> dict:
    user, _ = auth
    if user.profile.onboarding_step != "done":
        raise ApiError(409, "onboarding_required", "Finish onboarding before chatting with Rumi.")
    if not current_consents(db, user.id)["ai_chat"]:
        raise ApiError(409, "consent_required", "Allow the ai_chat consent first.", scope="ai_chat")
    api_key = settings.chat_server_api_key if purpose == "chat" else settings.chat_server_visit_prep_api_key
    if not settings.chat_server_url or not api_key:
        raise ApiError(503, "chat_server_unavailable", f"The {purpose} chat is not configured on this server.")
    try:
        if purpose == "visit_prep":
            # People are per tenant on the chat server, so the visit-prep tenant gets its own upsert.
            chat_server.onboard_person(str(user.id), chat_server.questionnaire(user.profile), api_key=api_key)
        elif user.profile.chat_synced_at is None:
            chat_server.sync_user(db, user.id)
            db.commit()
        token = chat_server.generate_token(api_key, str(user.id))
    except chat_server.ChatServerError as exc:
        raise ApiError(502, "chat_server_unavailable", "Rumi's chat server did not answer.") from exc
    return {"access_token": token, "expires_in": TOKEN_TTL, "socket_url": socket_url(), "tenant": TENANTS[purpose]}
