import json
from datetime import date
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select

from app import jobs, storage
from app.clock import age_on, now
from app.db import SessionLocal
from app.models import ChatServerOutbox, DataRequest, Job, Profile, User
from app.settings import settings

FULL_PROFILE = {
    "date_of_birth": "1974-03-12",
    "gender": "female",
    "location": "Arlington, VA",
    "timezone": "America/New_York",
    "profession": "Teacher",
    "reason": "Manage type 2 diabetes",
}


def complete_onboarding(client, headers):
    assert client.patch("/v1/me/profile", json=FULL_PROFILE, headers=headers).status_code == 200
    reply = client.post("/v1/me/onboarding/complete", headers=headers)
    assert reply.status_code == 200, reply.text
    return reply.json()


def outbox_rows():
    with SessionLocal() as db:
        return db.scalars(select(ChatServerOutbox)).all()


def test_get_me_returns_every_part_with_defaults(client, signed_in):
    body = client.get("/v1/me", headers=signed_in.headers).json()
    assert body["profile"]["first_name"] == "Elena" and body["profile"]["last_name"] == "Ruiz"
    assert body["profile"]["timezone"] is None and body["profile"]["updated_at"].endswith("Z")
    assert body["onboarding"] == {"step": "about_you", "completed_at": None, "answers": {"first_name": "Elena", "last_name": "Ruiz"}}
    assert body["preferences"] == {"tone": "straight_talk", "reply_length": "balanced", "ai_paused": False}
    assert body["notifications"] == {
        "categories": {"habit_moments": True, "insights": True, "heads_ups": True, "logistics": True, "check_ins": True},
        "quiet_start": 21,
        "quiet_end": 8,
        "channels": {"push": True, "sms": False, "call": False},
    }
    assert body["consents"] == {scope: False for scope in ("ai_chat", "ai_patient_facts", "health_records", "everyday_rhythms", "outreach_sms", "outreach_call")}


def test_patch_profile_changes_only_the_fields_sent(client, signed_in):
    reply = client.patch("/v1/me/profile", json={"preferred_name": "Ellie", "timezone": "America/Chicago"}, headers=signed_in.headers)
    assert reply.status_code == 200
    assert reply.json()["preferred_name"] == "Ellie"
    assert reply.json()["timezone"] == "America/Chicago"
    assert reply.json()["first_name"] == "Elena"

    bad_zone = client.patch("/v1/me/profile", json={"timezone": "Mars/Olympus"}, headers=signed_in.headers)
    assert bad_zone.status_code == 400
    assert bad_zone.json()["error"]["code"] == "invalid_request"
    assert "timezone" in bad_zone.json()["error"]["message"]

    unknown = client.patch("/v1/me/profile", json={"shoe_size": 9}, headers=signed_in.headers)
    assert unknown.status_code == 400

    future = client.patch("/v1/me/profile", json={"date_of_birth": "2999-01-01"}, headers=signed_in.headers)
    assert future.status_code == 400


def test_onboarding_saves_each_step_then_completes_and_syncs(client, signed_in, fake_chat_server):
    headers = signed_in.headers
    incomplete = client.post("/v1/me/onboarding/complete", headers=headers)
    assert incomplete.status_code == 400
    assert incomplete.json()["error"]["code"] == "onboarding_incomplete"
    assert incomplete.json()["error"]["fields"] == ["date_of_birth", "gender", "location", "timezone", "profession", "reason"]

    step = client.patch(
        "/v1/me/onboarding",
        json={"step": "about_you", "answers": {"date_of_birth": "1974-03-12", "gender": "female", "location": "Arlington, VA", "timezone": "America/New_York"}},
        headers=headers,
    )
    assert step.status_code == 200, step.text
    assert step.json()["step"] == "why_rumi"
    assert step.json()["answers"]["date_of_birth"] == "1974-03-12"

    step = client.patch("/v1/me/onboarding", json={"step": "why_rumi", "answers": {"reason": "Manage type 2 diabetes", "profession": "Teacher"}}, headers=headers)
    assert step.json()["step"] == "records"
    step = client.patch("/v1/me/onboarding", json={"step": "records"}, headers=headers)
    assert step.json()["step"] == "preferences"
    step = client.patch("/v1/me/onboarding", json={"step": "preferences", "answers": {"tone": "gentle_nudges"}}, headers=headers)
    assert step.json()["step"] == "preferences"
    assert client.get("/v1/me/preferences", headers=headers).json()["tone"] == "gentle_nudges"

    # Going back to an earlier step never moves the step backwards.
    step = client.patch("/v1/me/onboarding", json={"step": "about_you", "answers": {"location": "Alexandria, VA"}}, headers=headers)
    assert step.json()["step"] == "preferences"

    done = client.post("/v1/me/onboarding/complete", headers=headers)
    assert done.status_code == 200, done.text
    assert done.json()["step"] == "done" and done.json()["chat_synced"] is True
    assert done.json()["completed_at"].endswith("Z")
    assert client.get("/v1/auth/me", headers=headers).json()["onboarding_complete"] is True

    (call,) = fake_chat_server.calls
    assert call.url.path == "/chat/onboardPerson"
    sent = json.loads(call.content)
    assert sent["api_key"] == "chat-test-key"
    assert sent["external_ref"] == signed_in.user["id"]
    assert sent["onboarding_questionnaire"] == {
        "name": "Elena",
        "age": age_on(date(1974, 3, 12), date.today()),
        "gender": "female",
        "location": "Alexandria, VA",
        "profession": "Teacher",
        "reason": "Manage type 2 diabetes",
        "timezone": "America/New_York",
    }

    again = client.patch("/v1/me/onboarding", json={"step": "records"}, headers=headers)
    assert again.status_code == 400


def test_completion_still_succeeds_when_the_chat_server_is_down(client, signed_in, fake_chat_server):
    fake_chat_server.status = 500
    done = complete_onboarding(client, signed_in.headers)
    assert done["step"] == "done" and done["chat_synced"] is False

    (row,) = outbox_rows()
    assert (row.kind, row.status, row.payload) == ("sync", "pending", {"sections": ["profile"]})

    fake_chat_server.status = 200
    with SessionLocal() as db:
        assert jobs.run_outbox_one(db) is True
        assert db.get(ChatServerOutbox, row.id).status == "done"
        assert db.get(Profile, row.user_id).chat_synced_at is not None
    assert len(fake_chat_server.calls) == 2


def test_profile_changes_after_onboarding_queue_one_merged_sync(client, signed_in, fake_chat_server):
    headers = signed_in.headers
    complete_onboarding(client, headers)
    assert outbox_rows() == []

    client.patch("/v1/me/profile", json={"last_name": "Ruiz-Ortega"}, headers=headers)
    assert outbox_rows() == []

    client.patch("/v1/me/profile", json={"location": "Alexandria, VA"}, headers=headers)
    client.patch("/v1/me/preferences", json={"reply_length": "brief"}, headers=headers)
    rows = outbox_rows()
    assert len(rows) == 1 and rows[0].payload == {"sections": ["profile"]}

    empty = client.patch("/v1/me/profile", json={"gender": None}, headers=headers)
    assert empty.status_code == 400


def test_preferences_patch_and_validation(client, signed_in):
    reply = client.patch("/v1/me/preferences", json={"reply_length": "brief", "ai_paused": True}, headers=signed_in.headers)
    assert reply.json() == {"tone": "straight_talk", "reply_length": "brief", "ai_paused": True}
    assert client.patch("/v1/me/preferences", json={"tone": "shouty"}, headers=signed_in.headers).status_code == 400


def test_notifications_merge_and_need_consent_for_sms(client, signed_in):
    headers = signed_in.headers
    reply = client.patch("/v1/me/notifications", json={"categories": {"insights": False}, "quiet_start": 22}, headers=headers)
    assert reply.status_code == 200
    assert reply.json()["categories"]["insights"] is False and reply.json()["categories"]["logistics"] is True
    assert reply.json()["quiet_start"] == 22 and reply.json()["quiet_end"] == 8

    assert client.patch("/v1/me/notifications", json={"quiet_start": 24}, headers=headers).status_code == 400

    refused = client.patch("/v1/me/notifications", json={"channels": {"sms": True}}, headers=headers)
    assert refused.status_code == 409
    assert refused.json()["error"] == {"code": "consent_required", "message": "Allow the outreach_sms consent first.", "scope": "outreach_sms"}

    assert client.put("/v1/me/consents/outreach_sms", json={"granted": True, "policy_version": "2026-09"}, headers=headers).status_code == 200
    allowed = client.patch("/v1/me/notifications", json={"channels": {"sms": True}}, headers=headers)
    assert allowed.json()["channels"] == {"push": True, "sms": True, "call": False}

    client.put("/v1/me/consents/outreach_sms", json={"granted": False, "policy_version": "2026-09"}, headers=headers)
    assert client.get("/v1/me/notifications", headers=headers).json()["channels"]["sms"] is False


def test_consents_keep_a_history(client, signed_in):
    headers = signed_in.headers
    granted = client.put("/v1/me/consents/ai_chat", json={"granted": True, "policy_version": "2026-09"}, headers=headers)
    assert granted.status_code == 200
    assert granted.json()["scope"] == "ai_chat" and granted.json()["granted"] is True
    assert granted.json()["changed_at"].endswith("Z")

    unknown = client.put("/v1/me/consents/mind_reading", json={"granted": True, "policy_version": "2026-09"}, headers=headers)
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "unknown_scope"

    assert client.get("/v1/me/consents", headers=headers).json()["ai_chat"] is True
    client.put("/v1/me/consents/ai_chat", json={"granted": False, "policy_version": "2026-09"}, headers=headers)
    assert client.get("/v1/me/consents", headers=headers).json()["ai_chat"] is False

    page = client.get("/v1/me/consents/history?limit=1", headers=headers).json()
    assert len(page["items"]) == 1 and page["items"][0]["granted"] is False and page["items"][0]["platform"] == "ios"
    assert page["next_cursor"]
    rest = client.get(f"/v1/me/consents/history?limit=1&cursor={page['next_cursor']}", headers=headers).json()
    assert len(rest["items"]) == 1 and rest["items"][0]["granted"] is True and rest["next_cursor"] is None
    assert client.get("/v1/me/consents/history?cursor=garbage", headers=headers).status_code == 400


def test_export_runs_as_a_job_and_gives_a_download_link(client, signed_in, fake_storage):
    headers = signed_in.headers
    started = client.post("/v1/me/exports", headers=headers)
    assert started.status_code == 202
    export_id = started.json()["id"]
    assert started.json()["status"] == "pending"
    assert client.get(f"/v1/me/exports/{export_id}", headers=headers).json()["status"] == "pending"

    with SessionLocal() as db:
        assert jobs.run_one(db) is True
        assert jobs.run_one(db) is False

    ready = client.get(f"/v1/me/exports/{export_id}", headers=headers).json()
    assert ready["status"] == "ready"
    assert ready["download_url"].startswith("https://files.test/exports/")
    assert ready["expires_at"].endswith("Z")
    (key,) = fake_storage
    exported = json.loads(fake_storage[key])
    assert exported["user"]["email"] == "elena@example.com"
    assert exported["profile"]["first_name"] == "Elena"
    assert client.get("/v1/me/exports/00000000-0000-0000-0000-000000000000", headers=headers).status_code == 404


def test_without_s3_the_export_is_kept_on_disk_and_served_by_a_signed_link(client, signed_in, local_files):
    headers = signed_in.headers
    export_id = client.post("/v1/me/exports", headers=headers).json()["id"]
    with SessionLocal() as db:
        assert jobs.run_one(db) is True
    (written,) = local_files.rglob("*.json")
    assert written.name == f"{export_id}.json"

    link = urlsplit(client.get(f"/v1/me/exports/{export_id}", headers=headers).json()["download_url"])
    assert (link.scheme, link.netloc) == ("http", "localhost:8000") and link.path.startswith("/v1/files/local/exports/")
    # No Authorization header: the signature is enough.
    served = client.get(f"{link.path}?{link.query}")
    assert served.status_code == 200, served.text
    assert json.loads(served.content)["user"]["email"] == "elena@example.com"

    forged = client.get(f"{link.path}?{link.query.replace('signature=', 'signature=0')}")
    assert forged.status_code == 403 and forged.json()["error"]["code"] == "link_invalid"
    expired = storage.download_url("exports/x.json", -1)
    assert client.get(urlsplit(expired).path + "?" + urlsplit(expired).query).status_code == 403
    with pytest.raises(ValueError):
        storage.local_path("../secret.json")


def test_a_failing_export_is_retried_then_marked_failed(client, signed_in, monkeypatch):
    def broken(key, data, content_type):
        raise RuntimeError("S3_BUCKET is not set")

    monkeypatch.setattr(jobs.storage, "put_bytes", broken)
    monkeypatch.setattr(jobs, "MAX_ATTEMPTS", 2)
    export_id = client.post("/v1/me/exports", headers=signed_in.headers).json()["id"]
    with SessionLocal() as db:
        assert jobs.run_one(db) is True
        job = db.scalars(select(Job)).one()
        assert (job.status, job.attempts) == ("queued", 1) and "S3_BUCKET" in job.last_error
        job.run_at = now()
        db.commit()
        assert jobs.run_one(db) is True
        assert db.get(Job, job.id).status == "failed"
    assert client.get(f"/v1/me/exports/{export_id}", headers=signed_in.headers).json()["status"] == "failed"


def test_delete_ends_sessions_now_and_removes_data_in_the_background(client, signed_in, fake_chat_server):
    headers = signed_in.headers
    refused = client.request("DELETE", "/v1/me", headers=headers)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "confirmation_required"

    accepted = client.request("DELETE", "/v1/me", json={"confirm": "DELETE"}, headers=headers)
    assert accepted.status_code == 202
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
    assert client.post("/v1/auth/refresh", json={"refresh_token": signed_in.refresh_token}).status_code == 401

    with SessionLocal() as db:
        assert db.scalars(select(DataRequest)).one().kind == "delete"
        assert jobs.run_one(db) is True
        assert db.scalars(select(User)).all() == []
        (row,) = db.scalars(select(ChatServerOutbox)).all()
        assert (row.kind, row.status) == ("delete", "pending")
        assert jobs.run_outbox_one(db) is True
        row = db.get(ChatServerOutbox, row.id)
        assert row.status == "done"
    (call,) = fake_chat_server.calls
    assert call.url.path.endswith("/deletePerson")
    assert json.loads(call.content) == {"api_key": settings.chat_server_api_key, "external_ref": signed_in.user["id"]}


def test_a_person_the_chat_server_never_had_counts_as_deleted(client, signed_in, fake_chat_server):
    fake_chat_server.status = 404
    client.request("DELETE", "/v1/me", json={"confirm": "DELETE"}, headers=signed_in.headers)
    with SessionLocal() as db:
        assert jobs.run_one(db) is True
        assert jobs.run_outbox_one(db) is True
        assert db.scalars(select(ChatServerOutbox)).one().status == "done"


def test_a_chat_server_failure_keeps_the_delete_for_a_retry(client, signed_in, fake_chat_server):
    fake_chat_server.status = 500
    client.request("DELETE", "/v1/me", json={"confirm": "DELETE"}, headers=signed_in.headers)
    with SessionLocal() as db:
        assert jobs.run_one(db) is True
        assert jobs.run_outbox_one(db) is True
        row = db.scalars(select(ChatServerOutbox)).one()
        assert row.status == "pending" and row.attempts == 1 and "deletePerson returned 500" in row.last_error
