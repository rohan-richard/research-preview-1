from datetime import timedelta

from sqlalchemy import select, update

from app.clock import now
from app.db import SessionLocal
from app.models import AuthSession, User
from app.tokens import mint_access_token
from tests.conftest import bearer, sign_in


def test_sign_in_on_ios_creates_the_user_and_returns_tokens(client, fake_provider):
    body = sign_in(client, fake_provider).json()
    assert body["expires_in"] == 900
    assert body["refresh_token"].startswith("rt_")
    assert body["user"] == {
        "id": body["user"]["id"],
        "email": "elena@example.com",
        "display_name": "Elena R.",
        "status": "active",
        "onboarding_complete": False,
        "providers": ["google"],
        "created_at": body["user"]["created_at"],
    }
    assert body["user"]["created_at"].endswith("Z")
    me = client.get("/v1/auth/me", headers=bearer(body))
    assert me.status_code == 200
    assert me.json() == body["user"]


def test_sign_in_on_web_puts_the_refresh_token_in_a_cookie(client, fake_provider):
    reply = sign_in(client, fake_provider, platform="web")
    assert "refresh_token" not in reply.json()
    cookie = reply.headers["set-cookie"]
    assert cookie.startswith("rumi_refresh=rt_")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/v1/auth", "Max-Age=2592000"):
        assert flag in cookie, cookie


def test_a_second_provider_links_to_the_user_with_the_same_email(client, fake_provider):
    first = sign_in(client, fake_provider, token="g", provider="google", subject="g-1").json()
    second = sign_in(client, fake_provider, token="a", provider="apple", subject="a-1", given_name=None, family_name=None).json()
    assert second["user"]["id"] == first["user"]["id"]
    assert second["user"]["providers"] == ["apple", "google"]
    assert second["user"]["display_name"] == "Elena R."


def test_signing_in_again_reuses_the_user_and_opens_a_new_session(client, fake_provider):
    first = sign_in(client, fake_provider).json()
    second = sign_in(client, fake_provider).json()
    assert first["user"]["id"] == second["user"]["id"]
    with SessionLocal() as db:
        assert len(db.scalars(select(AuthSession)).all()) == 2


def test_apple_name_from_the_body_is_used_on_first_sign_in(client, fake_provider):
    fake_provider.add("a", provider="apple", subject="a-1", email="sam@privaterelay.appleid.com", given_name=None, family_name=None)
    reply = client.post(
        "/v1/auth/sign-in",
        json={"provider": "apple", "id_token": "a", "nonce": "n", "platform": "ios", "name": {"given": "Sam", "family": "Lee"}},
    )
    assert reply.json()["user"]["display_name"] == "Sam L."
    profile = client.get("/v1/me/profile", headers=bearer(reply.json())).json()
    assert (profile["first_name"], profile["last_name"]) == ("Sam", "Lee")


def test_a_bad_id_token_is_refused(client, fake_provider):
    reply = client.post("/v1/auth/sign-in", json={"provider": "google", "id_token": "nope", "nonce": "n", "platform": "ios"})
    assert reply.status_code == 401
    assert reply.json() == {"error": {"code": "invalid_id_token", "message": "The ID token failed a check."}}


def test_a_missing_field_is_an_invalid_request(client):
    reply = client.post("/v1/auth/sign-in", json={"provider": "google"})
    assert reply.status_code == 400
    assert reply.json()["error"]["code"] == "invalid_request"
    assert "id_token" in reply.json()["error"]["message"]


def test_refresh_on_ios_rotates_the_refresh_token(client, signed_in):
    old = signed_in.refresh_token
    first = client.post("/v1/auth/refresh", json={"refresh_token": old})
    assert first.status_code == 200
    new = first.json()["refresh_token"]
    assert new != old and first.json()["expires_in"] == 900
    assert client.get("/v1/auth/me", headers=bearer(first.json())).status_code == 200

    reused = client.post("/v1/auth/refresh", json={"refresh_token": old})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "session_expired"

    assert client.post("/v1/auth/refresh", json={"refresh_token": new}).status_code == 200


def test_refresh_on_web_uses_the_cookie(client, fake_provider):
    sign_in(client, fake_provider, platform="web")
    reply = client.post("/v1/auth/refresh")
    assert reply.status_code == 200, reply.text
    assert "refresh_token" not in reply.json()
    assert reply.headers["set-cookie"].startswith("rumi_refresh=rt_")


def test_refresh_without_a_token_is_session_expired(client):
    reply = client.post("/v1/auth/refresh")
    assert reply.status_code == 401
    assert reply.json()["error"]["code"] == "session_expired"


def test_an_expired_refresh_token_is_session_expired(client, signed_in):
    with SessionLocal() as db:
        db.execute(update(AuthSession).values(expires_at=now() - timedelta(seconds=1)))
        db.commit()
    reply = client.post("/v1/auth/refresh", json={"refresh_token": signed_in.refresh_token})
    assert reply.status_code == 401


def test_sign_out_ends_the_session(client, signed_in):
    assert client.post("/v1/auth/sign-out", headers=signed_in.headers).status_code == 204
    me = client.get("/v1/auth/me", headers=signed_in.headers)
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "access_token_invalid"
    assert client.post("/v1/auth/refresh", json={"refresh_token": signed_in.refresh_token}).status_code == 401


def test_sign_out_on_web_clears_the_cookie(client, fake_provider):
    body = sign_in(client, fake_provider, platform="web").json()
    reply = client.post("/v1/auth/sign-out", headers=bearer(body))
    assert reply.status_code == 204
    assert 'rumi_refresh=""' in reply.headers["set-cookie"] and "Max-Age=0" in reply.headers["set-cookie"]


def test_a_disabled_user_is_refused_everywhere(client, fake_provider, signed_in):
    with SessionLocal() as db:
        db.execute(update(User).values(status="disabled"))
        db.commit()
    for reply in (
        client.get("/v1/auth/me", headers=signed_in.headers),
        client.post("/v1/auth/refresh", json={"refresh_token": signed_in.refresh_token}),
        client.post("/v1/auth/sign-in", json={"provider": "google", "id_token": "tok-elena", "nonce": "n", "platform": "ios"}),
    ):
        assert reply.status_code == 403
        assert reply.json()["error"]["code"] == "account_disabled"


def test_routes_need_a_valid_access_token(client, signed_in):
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    with SessionLocal() as db:
        session = db.scalars(select(AuthSession)).one()
    stale = mint_access_token(session.user_id, session.id, at=now() - timedelta(minutes=20))
    reply = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {stale}"})
    assert reply.status_code == 401
    assert reply.json()["error"]["code"] == "access_token_invalid"


def test_health_reports_the_database(client):
    reply = client.get("/health")
    assert reply.status_code == 200
    assert reply.json() == {"ok": True, "database": "ok"}
    assert reply.headers["cache-control"] == "no-store"


def test_dev_sign_in_is_off_unless_enabled(client, monkeypatch):
    body = {"email": "Dev@Rumi.local", "platform": "ios"}
    assert client.post("/v1/auth/dev-sign-in", json=body).status_code == 404

    monkeypatch.setattr("app.auth.settings.dev_sign_in", True)
    reply = client.post("/v1/auth/dev-sign-in", json=body)
    assert reply.status_code == 200, reply.text
    assert reply.json()["user"]["email"] == "dev@rumi.local"
    assert reply.json()["user"]["providers"] == ["dev"]
    assert client.get("/v1/auth/me", headers=bearer(reply.json())).status_code == 200
