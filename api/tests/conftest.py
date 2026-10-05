import os
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://rumi:rumi@localhost:5432/rumi_test")
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 32
os.environ["GOOGLE_CLIENT_IDS"] = "google-test-client"
os.environ["APPLE_CLIENT_IDS"] = "apple-test-client"
os.environ["CORS_ORIGINS"] = ""
os.environ["CHAT_SERVER_URL"] = "http://chat.test/chat"
os.environ["CHAT_SERVER_API_KEY"] = "chat-test-key"
os.environ["S3_BUCKET"] = ""
os.environ["DEV_SIGN_IN"] = "0"
os.environ["FASTEN_PUBLIC_ID"] = ""
os.environ["FASTEN_PRIVATE_KEY"] = ""
os.environ["FASTEN_WEBHOOK_SECRET"] = ""
os.environ["FASTEN_API_URL"] = "https://api.connect.fastenhealth.com/v1"

import httpx  # noqa: E402
import pytest  # noqa: E402
import sqlalchemy  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import chat_server, providers, storage  # noqa: E402
from app.settings import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.providers import ProviderIdentity  # noqa: E402


def ensure_database() -> None:
    url = sqlalchemy.make_url(os.environ["DATABASE_URL"])
    admin = sqlalchemy.create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        found = connection.execute(text("select 1 from pg_database where datname = :name"), {"name": url.database}).scalar()
        if not found:
            connection.execute(text(f'create database "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    ensure_database()
    with engine.begin() as connection:
        connection.execute(text("drop schema public cascade"))
        connection.execute(text("create schema public"))
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine.begin() as connection:
        connection.execute(text("truncate " + ", ".join(t.name for t in Base.metadata.sorted_tables) + " cascade"))


@pytest.fixture(autouse=True)
def local_files(tmp_path, monkeypatch):
    # S3_BUCKET is empty here, so storage writes to disk. Keep that out of the real var/files.
    monkeypatch.setattr(settings, "local_files_dir", str(tmp_path / "files"))
    return tmp_path / "files"


@pytest.fixture
def client():
    # https so the Secure refresh cookie is sent back by the test client's cookie jar.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


class FakeProvider:
    def __init__(self):
        self.tokens: dict[str, ProviderIdentity] = {}

    def add(self, token: str, **fields) -> ProviderIdentity:
        defaults = dict(provider="google", subject="sub-1", email="elena@example.com", given_name="Elena", family_name="Ruiz")
        identity = ProviderIdentity(**{**defaults, **fields})
        self.tokens[token] = identity
        return identity

    def verify(self, provider: str, id_token: str, nonce: str) -> ProviderIdentity:
        identity = self.tokens.get(id_token)
        if identity is None or identity.provider != provider:
            raise ApiError(401, "invalid_id_token", "The ID token failed a check.")
        return identity


@pytest.fixture
def fake_provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(providers, "verify_id_token", fake.verify)
    return fake


def sign_in(client, fake_provider, token="tok-elena", platform="ios", **fields):
    identity = fake_provider.add(token, **fields)
    reply = client.post(
        "/v1/auth/sign-in",
        json={"provider": identity.provider, "id_token": token, "nonce": "nonce-1", "platform": platform},
    )
    assert reply.status_code == 200, reply.text
    return reply


def bearer(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture
def signed_in(client, fake_provider):
    body = sign_in(client, fake_provider).json()
    return SimpleNamespace(headers=bearer(body), refresh_token=body["refresh_token"], user=body["user"])


@pytest.fixture
def fake_chat_server(monkeypatch):
    fake = SimpleNamespace(calls=[], status=200)

    def handler(request: httpx.Request) -> httpx.Response:
        fake.calls.append(request)
        if request.url.path.endswith("/generateToken"):
            return httpx.Response(fake.status, json={"access_token": "chat-jwt-1"})
        return httpx.Response(fake.status, json={"tenant_id": "rumi-chat", "message": "success"})

    monkeypatch.setattr(chat_server, "client", httpx.Client(transport=httpx.MockTransport(handler)))
    return fake


@pytest.fixture
def fake_storage(monkeypatch):
    files: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, content_type: files.__setitem__(key, data))
    monkeypatch.setattr(storage, "download_url", lambda key, ttl_seconds: f"https://files.test/{key}?ttl={ttl_seconds}")
    monkeypatch.setattr(storage, "upload_url", lambda key, content_type, ttl_seconds: f"https://files.test/{key}?put={content_type}&ttl={ttl_seconds}")
    monkeypatch.setattr(storage, "exists", lambda key: key in files)
    monkeypatch.setattr(storage, "delete", lambda key: files.pop(key, None))
    return files
