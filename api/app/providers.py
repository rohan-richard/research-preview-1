from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from app.errors import ApiError
from app.settings import settings

JWKS_URLS = {
    "google": "https://www.googleapis.com/oauth2/v3/certs",
    "apple": "https://appleid.apple.com/auth/keys",
}
ISSUERS = {
    "google": ["https://accounts.google.com", "accounts.google.com"],
    "apple": ["https://appleid.apple.com"],
}


@dataclass
class ProviderIdentity:
    provider: str
    subject: str
    email: str
    given_name: str | None = None
    family_name: str | None = None


_jwks_clients: dict[str, PyJWKClient] = {}


def _signing_key(provider: str, id_token: str):
    client = _jwks_clients.get(provider)
    if client is None:
        client = _jwks_clients[provider] = PyJWKClient(JWKS_URLS[provider], cache_keys=True)
    return client.get_signing_key_from_jwt(id_token).key


def verify_id_token(provider: str, id_token: str, nonce: str) -> ProviderIdentity:
    audiences = settings.google_audiences if provider == "google" else settings.apple_audiences
    try:
        claims = jwt.decode(
            id_token,
            _signing_key(provider, id_token),
            algorithms=["RS256"],
            audience=audiences,
            issuer=ISSUERS[provider],
        )
    except jwt.PyJWTError as exc:
        raise ApiError(401, "invalid_id_token", "The ID token failed a check.") from exc
    if claims.get("nonce") != nonce:
        raise ApiError(401, "invalid_id_token", "The ID token nonce does not match.")
    email = claims.get("email")
    # Apple sends email_verified as the string "true" in older tokens.
    if not email or claims.get("email_verified") not in (True, "true"):
        raise ApiError(401, "invalid_id_token", "The ID token has no verified email.")
    return ProviderIdentity(
        provider=provider,
        subject=claims["sub"],
        email=email.lower(),
        given_name=claims.get("given_name"),
        family_name=claims.get("family_name"),
    )
