import uuid

from sqlalchemy import select

from app import jobs
from app.db import SessionLocal
from app.models import AuditLog
from tests.test_logs import add_log

FORWARDED = {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}


def audit_rows():
    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).order_by(AuditLog.at, AuditLog.id))
        return [(r.actor_type, r.actor_id, r.user_id, r.action, r.resource, r.resource_id, str(r.ip) if r.ip else None) for r in rows]


def test_a_profile_change_is_recorded_with_the_actor_and_ip(client, signed_in):
    headers = {**signed_in.headers, **FORWARDED}
    assert client.patch("/v1/me/profile", json={"preferred_name": "Ellie"}, headers=headers).status_code == 200
    user_id = uuid.UUID(signed_in.user["id"])
    assert audit_rows() == [("user", user_id, user_id, "update", "profiles", user_id, "203.0.113.9")]


def test_a_log_create_and_delete_are_recorded(client, signed_in):
    headers = signed_in.headers
    log = add_log(client, headers)
    assert client.delete(f"/v1/logs/{log['id']}", headers=headers).status_code == 204
    user_id = uuid.UUID(signed_in.user["id"])
    log_id = uuid.UUID(log["id"])
    # The test client has no real address, so ip is null here.
    assert audit_rows() == [
        ("user", user_id, user_id, "create", "logs", log_id, None),
        ("user", user_id, user_id, "delete", "logs", log_id, None),
    ]


def test_a_failed_write_records_nothing(client, signed_in):
    assert client.post("/v1/logs", json={"kind": "weight", "value": {"kg": "heavy"}, "taken_at": "2026-09-16T12:10:00Z"}, headers=signed_in.headers).status_code == 400
    assert client.get(f"/v1/logs/{uuid.uuid4()}", headers=signed_in.headers).status_code == 404
    assert audit_rows() == []


def test_a_list_of_clinical_data_is_recorded_as_a_read(client, signed_in):
    headers = signed_in.headers
    for path in ("/v1/logs", "/v1/appointments", "/v1/care-plans", "/v1/journeys"):
        assert client.get(path, headers=headers).status_code == 200
    assert client.get("/v1/logs/series?kind=weight", headers=headers).status_code == 200
    user_id = uuid.UUID(signed_in.user["id"])
    assert audit_rows() == [("user", user_id, user_id, "read", table, None, None) for table in ("logs", "appointments", "care_plans", "journeys")]


def test_an_export_is_recorded_by_the_route_and_by_the_worker(client, signed_in, fake_storage):
    headers = {**signed_in.headers, **FORWARDED}
    export_id = uuid.UUID(client.post("/v1/me/exports", headers=headers).json()["id"])
    with SessionLocal() as db:
        assert jobs.run_one(db) is True
    user_id = uuid.UUID(signed_in.user["id"])
    assert audit_rows() == [
        ("user", user_id, user_id, "export", "data_requests", export_id, "203.0.113.9"),
        ("system", None, user_id, "export", "data_requests", export_id, None),
    ]


def test_the_account_delete_is_recorded_and_the_rows_outlive_the_user(client, signed_in):
    headers = {**signed_in.headers, **FORWARDED}
    assert client.request("DELETE", "/v1/me", json={"confirm": "DELETE"}, headers=headers).status_code == 202
    with SessionLocal() as db:
        assert jobs.run_one(db) is True
    user_id = uuid.UUID(signed_in.user["id"])
    assert audit_rows() == [
        ("user", user_id, user_id, "delete", "users", user_id, "203.0.113.9"),
        ("system", None, user_id, "delete", "users", user_id, None),
    ]


def test_a_bad_forwarded_header_leaves_the_ip_empty(client, signed_in):
    headers = {**signed_in.headers, "X-Forwarded-For": "not-an-address"}
    assert client.patch("/v1/me/profile", json={"preferred_name": "Ellie"}, headers=headers).status_code == 200
    assert audit_rows()[0][-1] is None
