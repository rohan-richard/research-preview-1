import uuid
from datetime import timedelta

from sqlalchemy import select

from app import jobs, maintenance, storage
from app.clock import now
from app.db import SessionLocal
from app.models import DataRequest, File, IdempotencyKey, Log
from tests.test_files import start_upload
from tests.test_logs import add_log

OLD = now() - timedelta(hours=25)


def ids(model) -> set[uuid.UUID]:
    with SessionLocal() as db:
        return {row.id for row in db.scalars(select(model))}


def deleted_file(client, signed_in, fake_storage) -> tuple[uuid.UUID, str]:
    file = start_upload(client, signed_in.headers)
    key = f"files/{signed_in.user['id']}/{file['id']}"
    assert client.delete(f"/v1/files/{file['id']}", headers=signed_in.headers).status_code == 204
    # Pretend the first remove failed, so the object is still there for the tick.
    fake_storage[key] = b"jpeg bytes"
    return uuid.UUID(file["id"]), key


def test_the_tick_removes_what_is_older_than_a_day(client, signed_in, fake_storage):
    headers = signed_in.headers
    user_id = uuid.UUID(signed_in.user["id"])
    old_log, fresh_log = (add_log(client, {**headers, "Idempotency-Key": name}) for name in ("old", "fresh"))
    for log in (old_log, fresh_log):
        assert client.delete(f"/v1/logs/{log['id']}", headers=headers).status_code == 204
    (old_file, old_key), (fresh_file, fresh_key) = (deleted_file(client, signed_in, fake_storage) for _ in range(2))
    old_export, fresh_export = (uuid.UUID(client.post("/v1/me/exports", headers=headers).json()["id"]) for _ in range(2))
    with SessionLocal() as db:
        assert jobs.run_one(db) and jobs.run_one(db)

    with SessionLocal() as db:
        db.get(IdempotencyKey, (user_id, "old")).created_at = OLD
        db.get(Log, uuid.UUID(old_log["id"])).deleted_at = OLD
        db.get(File, old_file).deleted_at = OLD
        db.get(DataRequest, old_export).requested_at = OLD
        db.commit()
        maintenance.tick(db)

    with SessionLocal() as db:
        assert [row.key for row in db.scalars(select(IdempotencyKey))] == ["fresh"]
        assert db.get(DataRequest, old_export).status == "expired"
        assert db.get(DataRequest, fresh_export).status == "ready"
    assert ids(Log) == {uuid.UUID(fresh_log["id"])}
    assert ids(File) == {fresh_file}
    assert old_key not in fake_storage and fresh_key in fake_storage

    expired = client.get(f"/v1/me/exports/{old_export}", headers=headers).json()
    assert expired == {"id": str(old_export), "status": "expired"}
    assert "download_url" in client.get(f"/v1/me/exports/{fresh_export}", headers=headers).json()


def test_a_file_that_cannot_be_removed_waits_for_the_next_tick(client, signed_in, fake_storage, monkeypatch):
    file_id, key = deleted_file(client, signed_in, fake_storage)
    user_id = uuid.UUID(signed_in.user["id"])
    add_log(client, {**signed_in.headers, "Idempotency-Key": "old"})

    def broken(key):
        raise RuntimeError("S3 is down")

    monkeypatch.setattr(storage, "delete", broken)
    with SessionLocal() as db:
        db.get(File, file_id).deleted_at = OLD
        db.get(IdempotencyKey, (user_id, "old")).created_at = OLD
        db.commit()
        maintenance.tick(db)
    assert ids(File) == {file_id} and key in fake_storage
    with SessionLocal() as db:
        assert db.scalars(select(IdempotencyKey)).all() == []
