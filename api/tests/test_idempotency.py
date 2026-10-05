import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import DataRequest, File, GuideItem, IdempotencyKey, Journey, PushDevice
from tests.conftest import bearer, sign_in
from tests.test_journeys import add_habit, add_journey
from tests.test_visits import add_appointment

WEB_DEVICE = {"platform": "web", "subscription": {"endpoint": "https://push.test/sub/1", "keys": {"p256dh": "p", "auth": "a"}}}


def count(model) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(model)).all())


def stored_route(user_id: str, key: str) -> str:
    with SessionLocal() as db:
        return db.get(IdempotencyKey, (uuid.UUID(user_id), key)).route


def test_a_repeated_appointment_post_returns_the_first_one(client, signed_in):
    headers = {**signed_in.headers, "Idempotency-Key": "appt-1"}
    first = add_appointment(client, headers)
    assert add_appointment(client, headers) == first
    assert len(client.get("/v1/appointments", headers=headers).json()["items"]) == 1
    assert add_appointment(client, {**signed_in.headers, "Idempotency-Key": "appt-2"})["id"] != first["id"]
    assert add_appointment(client, signed_in.headers)["id"] not in (first["id"],)
    assert len(client.get("/v1/appointments", headers=headers).json()["items"]) == 3
    assert stored_route(signed_in.user["id"], "appt-1") == "POST /v1/appointments"


def test_a_repeated_journey_post_returns_the_first_one(client, signed_in):
    headers = {**signed_in.headers, "Idempotency-Key": "journey-1"}
    first = add_journey(client, headers)
    assert add_journey(client, headers) == first
    assert count(Journey) == 1

    habit = add_habit(client, {**signed_in.headers, "Idempotency-Key": "habit-1"}, first["id"])
    assert add_habit(client, {**signed_in.headers, "Idempotency-Key": "habit-1"}, first["id"]) == habit
    assert stored_route(signed_in.user["id"], "habit-1") == "POST /v1/journeys/{journey_id}/habits"


def test_the_stored_status_comes_back_too(client, signed_in):
    headers = {**signed_in.headers, "Idempotency-Key": "export-1"}
    first = client.post("/v1/me/exports", headers=headers)
    again = client.post("/v1/me/exports", headers=headers)
    assert first.status_code == again.status_code == 202 and first.json() == again.json()
    assert count(DataRequest) == 1


def test_guide_items_devices_and_files_honor_the_key(client, signed_in, fake_storage):
    for path, body, model in (
        ("/v1/guide-items", {"kind": "question", "text": "Is this normal?"}, GuideItem),
        ("/v1/push/devices", WEB_DEVICE, PushDevice),
        ("/v1/files", {"purpose": "document", "content_type": "application/pdf", "size_bytes": 1024}, File),
    ):
        headers = {**signed_in.headers, "Idempotency-Key": f"key-{path}"}
        first = client.post(path, json=body, headers=headers)
        assert first.status_code == 201, first.text
        again = client.post(path, json=body, headers=headers)
        assert again.status_code == 201 and again.json() == first.json()
        assert count(model) == 1


def test_a_failed_post_does_not_use_up_the_key(client, signed_in):
    headers = {**signed_in.headers, "Idempotency-Key": "appt-1"}
    bad = client.post("/v1/appointments", json={"kind": "video", "starts_at": "2026-10-10T10:00:00Z", "ends_at": "2026-10-10T09:00:00Z"}, headers=headers)
    assert bad.status_code == 400
    assert client.get("/v1/appointments", headers=headers).json()["items"] == []
    good = add_appointment(client, headers)
    assert add_appointment(client, headers) == good


def test_a_key_belongs_to_one_route(client, signed_in):
    headers = {**signed_in.headers, "Idempotency-Key": "shared"}
    add_journey(client, headers)
    reused = client.post("/v1/appointments", json={"kind": "video", "starts_at": "2026-10-10T10:00:00Z", "ends_at": "2026-10-10T11:00:00Z"}, headers=headers)
    assert reused.status_code == 400 and reused.json()["error"]["code"] == "invalid_request"
    assert "another route" in reused.json()["error"]["message"]


def test_keys_are_per_user(client, fake_provider, signed_in):
    mine = add_journey(client, {**signed_in.headers, "Idempotency-Key": "shared"})
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com").json())
    theirs = add_journey(client, {**other, "Idempotency-Key": "shared"})
    assert theirs["id"] != mine["id"]
    assert count(Journey) == 2
    assert client.get(f"/v1/journeys/{mine['id']}", headers=other).status_code == 404
