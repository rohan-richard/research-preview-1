import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

import jwt

from app.clock import now
from app.settings import settings

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)


def mint_access_token(user_id: uuid.UUID, session_id: uuid.UUID, at: datetime | None = None) -> str:
    at = at or now()
    claims = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": int(at.timestamp()),
        "exp": int((at + ACCESS_TTL).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def read_access_token(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_refresh_token() -> str:
    return "rt_" + secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
