import uuid

from sqlalchemy import select

from app import storage
from app.db import SessionLocal
from app.models import File
from tests.conftest import bearer, sign_in

PHOTO = {"purpose": "log_photo", "content_type": "image/jpeg", "size_bytes": 824113}
LIMIT = 20 * 1024 * 1024


def start_upload(client, headers, **fields):
    reply = client.post("/v1/files", json={**PHOTO, **fields}, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def file_rows():
    with SessionLocal() as db:
        return db.scalars(select(File)).all()


def test_start_upload_gives_a_signed_put_link(client, signed_in, fake_storage):
    out = start_upload(client, signed_in.headers)
    (row,) = file_rows()
    key = f"files/{signed_in.user['id']}/{row.id}"
    assert out == {"id": str(row.id), "upload_url": f"https://files.test/{key}?put=image/jpeg&ttl=900", "expires_at": out["expires_at"]}
    assert out["expires_at"].endswith("Z")
    assert (row.purpose, row.content_type, row.size_bytes, row.status, row.storage_key) == ("log_photo", "image/jpeg", 824113, "pending", key)
    assert row.deleted_at is None


def test_the_size_limit_and_the_purpose_are_checked(client, signed_in, fake_storage):
    headers = signed_in.headers
    too_big = client.post("/v1/files", json={**PHOTO, "size_bytes": LIMIT + 1}, headers=headers)
    assert too_big.status_code == 400 and too_big.json()["error"]["code"] == "invalid_request"
    assert "size_bytes" in too_big.json()["error"]["message"]
    assert client.post("/v1/files", json={**PHOTO, "size_bytes": LIMIT}, headers=headers).status_code == 201
    assert client.post("/v1/files", json={**PHOTO, "size_bytes": 0}, headers=headers).status_code == 400

    unknown = client.post("/v1/files", json={**PHOTO, "purpose": "selfie"}, headers=headers)
    assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "invalid_request"
    assert "purpose" in unknown.json()["error"]["message"]
    assert client.post("/v1/files", json={**PHOTO, "content_type": "not a type"}, headers=headers).status_code == 400
    assert client.post("/v1/files", json={**PHOTO, "name": "photo.jpg"}, headers=headers).status_code == 400
    assert len(file_rows()) == 1


def test_download_waits_for_the_upload_then_marks_the_file_ready(client, signed_in, fake_storage):
    headers = signed_in.headers
    file = start_upload(client, headers)
    url = f"/v1/files/{file['id']}"
    not_ready = client.get(url, headers=headers)
    assert not_ready.status_code == 409 and not_ready.json()["error"]["code"] == "file_not_ready"
    assert file_rows()[0].status == "pending"

    key = f"files/{signed_in.user['id']}/{file['id']}"
    fake_storage[key] = b"jpeg bytes"
    ready = client.get(url, headers=headers)
    assert ready.status_code == 200, ready.text
    assert ready.json()["download_url"] == f"https://files.test/{key}?ttl=600"
    assert ready.json()["expires_at"].endswith("Z")
    assert file_rows()[0].status == "ready"

    # A ready file does not ask storage again.
    del fake_storage[key]
    assert client.get(url, headers=headers).status_code == 200


def test_delete_hides_the_file_and_removes_the_object(client, signed_in, fake_storage):
    headers = signed_in.headers
    file = start_upload(client, headers)
    key = f"files/{signed_in.user['id']}/{file['id']}"
    fake_storage[key] = b"jpeg bytes"
    assert client.delete(f"/v1/files/{file['id']}", headers=headers).status_code == 204
    assert key not in fake_storage
    assert client.get(f"/v1/files/{file['id']}", headers=headers).status_code == 404
    assert client.delete(f"/v1/files/{file['id']}", headers=headers).status_code == 404
    (row,) = file_rows()
    assert row.deleted_at is not None


def test_a_storage_error_does_not_stop_the_delete(client, signed_in, fake_storage, monkeypatch):
    def broken(key):
        raise RuntimeError("S3 is down")

    monkeypatch.setattr(storage, "delete", broken)
    file = start_upload(client, signed_in.headers)
    assert client.delete(f"/v1/files/{file['id']}", headers=signed_in.headers).status_code == 204
    assert file_rows()[0].deleted_at is not None


def test_another_users_file_is_not_found(client, fake_provider, signed_in, fake_storage):
    file = start_upload(client, signed_in.headers)
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com").json())
    assert client.get(f"/v1/files/{file['id']}", headers=other).status_code == 404
    assert client.delete(f"/v1/files/{file['id']}", headers=other).status_code == 404
    assert client.get(f"/v1/files/{uuid.uuid4()}", headers=signed_in.headers).status_code == 404
    assert file_rows()[0].deleted_at is None
