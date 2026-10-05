from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import providers
from app.clock import iso, now
from app.db import get_db
from app.errors import ApiError
from app.models import AuthSession, Identity, Profile, User, UserSettings
from app.providers import ProviderIdentity
from app.settings import settings
from app.tokens import ACCESS_TTL, REFRESH_TTL, hash_refresh_token, mint_access_token, new_refresh_token, read_access_token

router = APIRouter(prefix="/v1/auth")
COOKIE = "rumi_refresh"
COOKIE_PATH = "/v1/auth"

bearer = HTTPBearer(auto_error=False)


class NameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    given: str | None = None
    family: str | None = None


class SignInBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["google", "apple"]
    id_token: str
    nonce: str
    platform: Literal["web", "ios"]
    name: NameBody | None = None


class DevSignInBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    platform: Literal["web", "ios"]
    name: NameBody | None = None


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str | None = None


def user_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "status": user.status,
        "onboarding_complete": user.profile.onboarding_step == "done",
        "providers": sorted(identity.provider for identity in user.identities),
        "created_at": iso(user.created_at),
    }


def display_name(identity: ProviderIdentity, name: NameBody | None) -> str:
    given = (name and name.given) or identity.given_name
    family = (name and name.family) or identity.family_name
    if given and family:
        return f"{given} {family[0]}."
    return given or identity.email.split("@")[0]


def find_or_create_user(db: Session, identity: ProviderIdentity, name: NameBody | None) -> User:
    existing = db.scalar(select(Identity).where(Identity.provider == identity.provider, Identity.subject == identity.subject))
    if existing is not None:
        return existing.user
    user = db.scalar(select(User).where(User.email == identity.email))
    if user is None:
        user = User(email=identity.email, display_name=display_name(identity, name))
        user.profile = Profile(
            first_name=(name and name.given) or identity.given_name,
            last_name=(name and name.family) or identity.family_name,
        )
        user.settings = UserSettings()
        db.add(user)
    user.identities.append(Identity(provider=identity.provider, subject=identity.subject, email=identity.email))
    db.flush()
    return user


def start_session(db: Session, user: User, platform: str) -> tuple[AuthSession, str]:
    token = new_refresh_token()
    session = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(token),
        platform=platform,
        expires_at=now() + REFRESH_TTL,
    )
    db.add(session)
    db.flush()
    return session, token


def set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE, token, max_age=int(REFRESH_TTL.total_seconds()), path=COOKIE_PATH, secure=True, httponly=True, samesite="strict"
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict")


def token_response(response: Response, session: AuthSession, refresh_token: str) -> dict:
    body = {"access_token": mint_access_token(session.user_id, session.id), "expires_in": int(ACCESS_TTL.total_seconds())}
    if session.platform == "web":
        set_cookie(response, refresh_token)
    else:
        body["refresh_token"] = refresh_token
    return body


def current_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> tuple[User, AuthSession]:
    invalid = ApiError(401, "access_token_invalid", "The access token is missing or expired.")
    if credentials is None:
        raise invalid
    ids = read_access_token(credentials.credentials)
    if ids is None:
        raise invalid
    user_id, session_id = ids
    session = db.get(AuthSession, session_id)
    if session is None or session.user_id != user_id or session.revoked_at is not None:
        raise invalid
    if session.user.status == "disabled":
        raise ApiError(403, "account_disabled", "This account is disabled.")
    return session.user, session


Auth = Annotated[tuple[User, AuthSession], Depends(current_auth)]
DB = Annotated[Session, Depends(get_db)]


@router.post("/sign-in")
def sign_in(body: SignInBody, response: Response, db: DB) -> dict:
    identity = providers.verify_id_token(body.provider, body.id_token, body.nonce)
    user = find_or_create_user(db, identity, body.name)
    if user.status == "disabled":
        raise ApiError(403, "account_disabled", "This account is disabled.")
    session, refresh_token = start_session(db, user, body.platform)
    db.commit()
    return token_response(response, session, refresh_token) | {"user": user_payload(user)}


@router.post("/dev-sign-in", include_in_schema=settings.dev_sign_in)
def dev_sign_in(body: DevSignInBody, response: Response, db: DB) -> dict:
    if not settings.dev_sign_in:
        raise ApiError(404, "not_found", "Not Found")
    identity = ProviderIdentity(provider="dev", subject=body.email.lower(), email=body.email.lower())
    user = find_or_create_user(db, identity, body.name)
    session, refresh_token = start_session(db, user, body.platform)
    db.commit()
    return token_response(response, session, refresh_token) | {"user": user_payload(user)}


@router.post("/refresh")
def refresh(
    response: Response,
    db: DB,
    body: RefreshBody | None = None,
    cookie_token: Annotated[str | None, Cookie(alias=COOKIE)] = None,
) -> dict:
    token = (body.refresh_token if body else None) or cookie_token
    expired = ApiError(401, "session_expired", "Sign in again.")
    if not token:
        raise expired
    session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == hash_refresh_token(token)))
    if session is None or session.revoked_at is not None or session.expires_at <= now():
        raise expired
    if session.user.status == "disabled":
        raise ApiError(403, "account_disabled", "This account is disabled.")
    refresh_token = new_refresh_token()
    session.refresh_token_hash = hash_refresh_token(refresh_token)
    session.expires_at = now() + REFRESH_TTL
    db.commit()
    return token_response(response, session, refresh_token)


@router.post("/sign-out", status_code=204)
def sign_out(response: Response, auth: Auth, db: DB) -> None:
    _, session = auth
    session.revoked_at = now()
    db.commit()
    if session.platform == "web":
        clear_cookie(response)


@router.get("/me")
def me(auth: Auth) -> dict:
    user, _ = auth
    return user_payload(user)
