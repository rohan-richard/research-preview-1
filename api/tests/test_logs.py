import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import maintenance
from app.clock import now
from app.db import SessionLocal
from app.models import IdempotencyKey, Log
from tests.conftest import bearer, sign_in


def add_log(client, headers, **fields):
    body = {"kind": "blood_pressure", "value": {"systolic": 138, "diastolic": 84}, "taken_at": "2026-09-16T12:10:00Z", **fields}
    reply = client.post("/v1/logs", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def ids(reply) -> list[str]:
    return [item["id"] for item in reply.json()["items"]]


def log_rows():
    with SessionLocal() as db:
        return db.scalars(select(Log)).all()


def test_add_log_returns_it_and_a_repeated_key_returns_the_same_log(client, signed_in):
    headers = {**signed_in.headers, "Idempotency-Key": "k-1"}
    body = {"kind": "blood_pressure", "value": {"systolic": 138, "diastolic": 84}, "taken_at": "2026-09-16T12:10:00Z", "note": "After coffee"}
    first = client.post("/v1/logs", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert first.json() == {
        "id": first.json()["id"],
        "kind": "blood_pressure",
        "value": {"systolic": 138, "diastolic": 84},
        "taken_at": "2026-09-16T12:10:00Z",
        "note": "After coffee",
        "source": "patient",
        "created_at": first.json()["created_at"],
    }
    assert first.json()["created_at"].endswith("Z")

    again = client.post("/v1/logs", json=body, headers=headers)
    assert again.status_code == 201 and again.json() == first.json()
    assert len(log_rows()) == 1

    other_key = client.post("/v1/logs", json=body, headers={**signed_in.headers, "Idempotency-Key": "k-2"})
    assert other_key.status_code == 201 and other_key.json()["id"] != first.json()["id"]
    no_key = client.post("/v1/logs", json=body, headers=signed_in.headers)
    assert no_key.status_code == 201 and no_key.json()["id"] not in (first.json()["id"], other_key.json()["id"])
    assert len(log_rows()) == 3


def test_a_failed_post_does_not_use_up_the_key(client, signed_in):
    headers = {**signed_in.headers, "Idempotency-Key": "k-1"}
    bad = client.post("/v1/logs", json={"kind": "weight", "value": {"kg": "heavy"}, "taken_at": "2026-09-16T12:10:00Z"}, headers=headers)
    assert bad.status_code == 400
    good = client.post("/v1/logs", json={"kind": "weight", "value": {"kg": 81.4}, "taken_at": "2026-09-16T12:10:00Z"}, headers=headers)
    assert good.status_code == 201 and good.json()["value"] == {"kg": 81.4}


def test_idempotency_keys_are_per_user_and_expire_after_a_day(client, fake_provider, signed_in):
    body = {"kind": "note", "value": {"text": "Felt tired after lunch"}, "taken_at": "2026-09-16T12:10:00Z"}
    mine = client.post("/v1/logs", json=body, headers={**signed_in.headers, "Idempotency-Key": "shared"}).json()
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com").json())
    theirs = client.post("/v1/logs", json=body, headers={**other, "Idempotency-Key": "shared"}).json()
    assert theirs["id"] != mine["id"]
    assert client.get(f"/v1/logs/{mine['id']}", headers=other).status_code == 404

    with SessionLocal() as db:
        key = db.get(IdempotencyKey, (uuid.UUID(signed_in.user["id"]), "shared"))
        key.created_at = now() - timedelta(hours=25)
        db.commit()
        maintenance.run(db)
    fresh = client.post("/v1/logs", json=body, headers={**signed_in.headers, "Idempotency-Key": "shared"}).json()
    assert fresh["id"] != mine["id"]


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("blood_pressure", {"systolic": 138, "diastolic": 84, "pulse": 72}),
        ("glucose", {"mg_dl": 126, "timing": "fasting"}),
        ("weight", {"kg": 81.4}),
        ("symptom", {"name": "Leg cramps", "severity": 4, "body_region": "left_calf"}),
        ("medication_taken", {"medication_id": "0192f3c2-0000-7000-8000-000000000001", "status": "taken"}),
        ("meal", {"description": "Oatmeal with blueberries"}),
        ("activity", {"description": "Walk", "minutes": 20}),
        ("note", {"text": "Felt tired after lunch"}),
    ],
)
def test_each_kind_accepts_its_value_shape(client, signed_in, kind, value):
    log = add_log(client, signed_in.headers, kind=kind, value=value)
    assert log["kind"] == kind and log["value"] == value
    if kind == "medication_taken":
        assert str(log_rows()[0].medication_id) == value["medication_id"]


@pytest.mark.parametrize(
    ("kind", "value", "field"),
    [
        ("blood_pressure", {"systolic": 20, "diastolic": 84}, "value.systolic"),
        ("blood_pressure", {"systolic": 138}, "value.diastolic"),
        ("blood_pressure", {"systolic": 138, "diastolic": 84, "unit": "kPa"}, "value.unit"),
        ("glucose", {"mg_dl": 126}, "value.timing"),
        ("glucose", {"mg_dl": 7.1, "timing": "fasting"}, "value.mg_dl"),
        ("weight", {"kg": "heavy"}, "value.kg"),
        ("weight", {"kg": 0}, "value.kg"),
        ("symptom", {"name": "Leg cramps", "severity": 11}, "value.severity"),
        ("medication_taken", {"medication_id": "not-a-uuid", "status": "taken"}, "value.medication_id"),
        ("medication_taken", {"medication_id": "0192f3c2-0000-7000-8000-000000000001", "status": "forgot"}, "value.status"),
        ("meal", {"description": ""}, "value.description"),
        ("activity", {"description": "Walk", "minutes": 0}, "value.minutes"),
        ("note", {}, "value.text"),
    ],
)
def test_a_bad_value_names_the_field(client, signed_in, kind, value, field):
    reply = client.post("/v1/logs", json={"kind": kind, "value": value, "taken_at": "2026-09-16T12:10:00Z"}, headers=signed_in.headers)
    assert reply.status_code == 400, reply.text
    assert reply.json()["error"]["code"] == "invalid_value" and reply.json()["error"]["field"] == field
    assert reply.json()["error"]["message"]
    assert log_rows() == []


def test_the_rest_of_the_body_is_checked_too(client, signed_in):
    headers = signed_in.headers
    unknown_kind = client.post("/v1/logs", json={"kind": "mood", "value": {"text": "ok"}, "taken_at": "2026-09-16T12:10:00Z"}, headers=headers)
    assert unknown_kind.status_code == 400 and unknown_kind.json()["error"]["code"] == "invalid_request"
    naive = client.post("/v1/logs", json={"kind": "note", "value": {"text": "ok"}, "taken_at": "2026-09-16T12:10:00"}, headers=headers)
    assert naive.status_code == 400
    assert client.post("/v1/logs", json={"kind": "note", "value": {"text": "ok"}}, headers=headers).status_code == 400
    extra = client.post("/v1/logs", json={"kind": "note", "value": {"text": "ok"}, "taken_at": "2026-09-16T12:10:00Z", "source": "device"}, headers=headers)
    assert extra.status_code == 400


def test_list_is_newest_first_with_filters_and_pages(client, signed_in):
    headers = signed_in.headers
    august = add_log(client, headers, kind="weight", value={"kg": 82}, taken_at="2026-08-31T23:59:59Z")
    first = add_log(client, headers, taken_at="2026-09-01T00:00:00Z")
    middle = add_log(client, headers, kind="symptom", value={"name": "Leg cramps", "severity": 4}, taken_at="2026-09-15T12:00:00Z")
    last = add_log(client, headers, taken_at="2026-09-30T23:59:00Z")
    october = add_log(client, headers, kind="symptom", value={"name": "Headache", "severity": 2}, taken_at="2026-10-01T00:00:00Z")

    assert ids(client.get("/v1/logs", headers=headers)) == [october["id"], last["id"], middle["id"], first["id"], august["id"]]
    assert ids(client.get("/v1/logs?kind=symptom", headers=headers)) == [october["id"], middle["id"]]
    assert ids(client.get("/v1/logs?from=2026-09-01&to=2026-09-30", headers=headers)) == [last["id"], middle["id"], first["id"]]
    assert ids(client.get("/v1/logs?kind=symptom&from=2026-09-01&to=2026-09-30", headers=headers)) == [middle["id"]]
    assert client.get("/v1/logs?kind=mood", headers=headers).status_code == 400
    assert client.get("/v1/logs?from=yesterday", headers=headers).status_code == 400

    page = client.get("/v1/logs?limit=2", headers=headers).json()
    assert [item["id"] for item in page["items"]] == [october["id"], last["id"]] and page["next_cursor"]
    rest = client.get(f"/v1/logs?limit=2&cursor={page['next_cursor']}", headers=headers).json()
    assert [item["id"] for item in rest["items"]] == [middle["id"], first["id"]] and rest["next_cursor"]
    tail = client.get(f"/v1/logs?limit=2&cursor={rest['next_cursor']}", headers=headers).json()
    assert [item["id"] for item in tail["items"]] == [august["id"]] and tail["next_cursor"] is None
    assert client.get("/v1/logs?cursor=garbage", headers=headers).status_code == 400


def test_get_and_patch_one_log(client, signed_in, fake_provider):
    headers = signed_in.headers
    log = add_log(client, headers, note="After coffee")
    url = f"/v1/logs/{log['id']}"
    assert client.get(url, headers=headers).json() == log

    edited = client.patch(url, json={"value": {"systolic": 134, "diastolic": 84}}, headers=headers)
    assert edited.status_code == 200, edited.text
    assert edited.json()["value"] == {"systolic": 134, "diastolic": 84} and edited.json()["note"] == "After coffee"
    moved = client.patch(url, json={"taken_at": "2026-09-16T13:00:00Z", "note": None}, headers=headers)
    assert moved.json()["taken_at"] == "2026-09-16T13:00:00Z" and moved.json()["note"] is None

    wrong_shape = client.patch(url, json={"value": {"kg": 80}}, headers=headers)
    assert wrong_shape.status_code == 400 and wrong_shape.json()["error"]["code"] == "invalid_value"
    assert wrong_shape.json()["error"]["field"] == "value.systolic"
    assert client.patch(url, json={"kind": "weight"}, headers=headers).status_code == 400
    assert client.get("/v1/logs/00000000-0000-0000-0000-000000000000", headers=headers).status_code == 404

    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com").json())
    assert client.get(url, headers=other).status_code == 404
    assert client.patch(url, json={"note": "mine now"}, headers=other).status_code == 404
    assert client.delete(url, headers=other).status_code == 404


def test_delete_hides_then_restore_brings_back_until_a_day_passes(client, signed_in):
    headers = signed_in.headers
    log = add_log(client, headers)
    url = f"/v1/logs/{log['id']}"
    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url, headers=headers).status_code == 404
    assert client.get("/v1/logs", headers=headers).json()["items"] == []
    assert client.get("/v1/logs/series?kind=blood_pressure", headers=headers).json()["points"] == []
    assert client.delete(url, headers=headers).status_code == 404

    restored = client.post(f"{url}/restore", headers=headers)
    assert restored.status_code == 200 and restored.json()["id"] == log["id"]
    assert ids(client.get("/v1/logs", headers=headers)) == [log["id"]]
    assert client.post(f"{url}/restore", headers=headers).status_code == 200

    assert client.delete(url, headers=headers).status_code == 204
    with SessionLocal() as db:
        row = db.get(Log, uuid.UUID(log["id"]))
        row.deleted_at = now() - timedelta(hours=25)
        db.commit()
    expired = client.post(f"{url}/restore", headers=headers)
    assert expired.status_code == 410 and expired.json()["error"]["code"] == "restore_expired"

    # The hourly cleanup removes logs that were deleted more than a day ago.
    with SessionLocal() as db:
        maintenance.run(db)
    assert log_rows() == []
    assert client.post(f"{url}/restore", headers=headers).status_code == 404


def test_series_gives_chart_points_in_time_order(client, signed_in):
    headers = signed_in.headers
    add_log(client, headers, value={"systolic": 140, "diastolic": 90, "pulse": 70}, taken_at="2026-09-20T08:00:00Z")
    add_log(client, headers, taken_at="2026-09-16T12:10:00Z")
    add_log(client, headers, kind="glucose", value={"mg_dl": 126, "timing": "fasting"}, taken_at="2026-09-16T07:00:00Z")
    add_log(client, headers, kind="weight", value={"kg": 81.4}, taken_at="2026-07-01T07:00:00Z")
    add_log(client, headers, kind="weight", value={"kg": 80.9}, taken_at="2026-08-01T07:00:00Z")

    pressure = client.get("/v1/logs/series?kind=blood_pressure", headers=headers).json()
    assert pressure == {
        "kind": "blood_pressure",
        "unit": "mmHg",
        "points": [
            {"taken_at": "2026-09-16T12:10:00Z", "systolic": 138, "diastolic": 84, "source": "patient"},
            {"taken_at": "2026-09-20T08:00:00Z", "systolic": 140, "diastolic": 90, "pulse": 70, "source": "patient"},
        ],
    }
    glucose = client.get("/v1/logs/series?kind=glucose", headers=headers).json()
    assert glucose["unit"] == "mg/dL" and glucose["points"] == [{"taken_at": "2026-09-16T07:00:00Z", "mg_dl": 126, "timing": "fasting", "source": "patient"}]
    weight = client.get("/v1/logs/series?kind=weight&from=2026-07-15&to=2026-09-30", headers=headers).json()
    assert weight["unit"] == "kg" and weight["points"] == [{"taken_at": "2026-08-01T07:00:00Z", "kg": 80.9, "source": "patient"}]

    assert client.get("/v1/logs/series?kind=symptom", headers=headers).status_code == 400
    assert client.get("/v1/logs/series", headers=headers).status_code == 400
