import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import providers
from app.errors import ApiError

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
REAL_SIGNING_KEY = providers._signing_key


@pytest.fixture(autouse=True)
def local_signing_key(monkeypatch):
    monkeypatch.setattr(providers, "_signing_key", lambda provider, id_token: KEY.public_key())


def id_token(**claims) -> str:
    base = {
        "iss": "https://accounts.google.com",
        "aud": "google-test-client",
        "sub": "google-sub-1",
        "email": "Elena@Example.com",
        "email_verified": True,
        "nonce": "nonce-1",
        "given_name": "Elena",
        "family_name": "Ruiz",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    return jwt.encode({**base, **claims}, KEY, algorithm="RS256")


def test_a_good_google_token_gives_the_identity():
    identity = providers.verify_id_token("google", id_token(), "nonce-1")
    assert identity == providers.ProviderIdentity("google", "google-sub-1", "elena@example.com", "Elena", "Ruiz")


def test_a_good_apple_token_accepts_the_string_email_verified():
    token = id_token(iss="https://appleid.apple.com", aud="apple-test-client", sub="apple-sub-1", email_verified="true", given_name=None, family_name=None)
    identity = providers.verify_id_token("apple", token, "nonce-1")
    assert identity.provider == "apple" and identity.subject == "apple-sub-1" and identity.given_name is None


@pytest.mark.parametrize(
    "provider, claims, nonce",
    [
        ("google", {"aud": "someone-elses-client"}, "nonce-1"),
        ("google", {"iss": "https://appleid.apple.com"}, "nonce-1"),
        ("google", {"exp": int(time.time()) - 10}, "nonce-1"),
        ("google", {}, "other-nonce"),
        ("google", {"email_verified": False}, "nonce-1"),
        ("google", {"email": None}, "nonce-1"),
        ("apple", {"iss": "https://appleid.apple.com", "aud": "google-test-client"}, "nonce-1"),
    ],
)
def test_bad_tokens_are_refused(provider, claims, nonce):
    with pytest.raises(ApiError) as refused:
        providers.verify_id_token(provider, id_token(**claims), nonce)
    assert refused.value.status == 401 and refused.value.code == "invalid_id_token"


def test_garbage_is_refused_without_a_network_call(monkeypatch):
    monkeypatch.setattr(providers, "_signing_key", REAL_SIGNING_KEY)
    with pytest.raises(ApiError):
        providers.verify_id_token("google", "not-a-jwt", "nonce-1")
