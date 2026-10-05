import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app import notifications, push_send
from app.db import SessionLocal
from app.models import Notification, NotificationDelivery, PushDevice, UserSettings
from app.settings import settings
from tests.conftest import bearer, sign_in

UTC = timezone.utc
# A Friday. 16:00 UTC is noon in New York in July.
NOON = datetime(2026, 7, 3, 16, 0, tzinfo=UTC)
WEB = {
    "platform": "web",
    "subscription": {"endpoint": "https://push.test/sub/1", "keys": {"p256dh": "p256-key", "auth": "auth-key"}},
    "name": "Chrome on Mac",
}
IOS = {"platform": "ios", "apns_token": "a1b2c3d4e5f6", "environment": "sandbox", "name": "iPhone"}
NUDGE = {"tenant_id": "rumi-chat", "content": "How did the walk go?", "idempotency_key": "nudge-1"}
HOOK = {"X-Rumi-Webhook-Secret": "hook-secret"}


@pytest.fixture
def fake_push(monkeypatch):
    fake = SimpleNamespace(calls=[], fail=None)

    def sender(platform):
        def send(device, payload):
            fake.calls.append((platform, device.id, payload))
            if fake.fail is not None:
                raise fake.fail

        return send

    monkeypatch.setattr(push_send, "send_web", sender("web"))
    monkeypatch.setattr(push_send, "send_apns", sender("ios"))
    return fake


@pytest.fixture
def hook_secret(monkeypatch):
    monkeypatch.setattr(settings, "chat_server_webhook_secret", "hook-secret")


def register(client, headers, body=WEB):
    reply = client.post("/v1/push/devices", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def add_habit(client, headers, **fields):
    journey = client.post("/v1/journeys", json={"title": "Keep moving"}, headers=headers).json()
    reply = client.post(f"/v1/journeys/{journey['id']}/habits", json={"title": "10-minute walk", **fields}, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def add_appointment(client, headers, starts_at, **fields):
    body = {"kind": "video", "starts_at": starts_at.isoformat(), "ends_at": (starts_at + timedelta(hours=1)).isoformat(), **fields}
    reply = client.post("/v1/appointments", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def add_row(user_id, **fields) -> uuid.UUID:
    row = Notification(
        user_id=uuid.UUID(user_id),
        source="chat_nudge",
        category="check_ins",
        title="Rumi",
        body="How did the walk go?",
        link="/chat",
        scheduled_for=NOON - timedelta(minutes=1),
    )
    for field, value in fields.items():
        setattr(row, field, value)
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        return row.id


def add_sent(user_id, sent_at, count=1, source="chat_nudge"):
    for _ in range(count):
        add_row(user_id, source=source, status="sent", sent_at=sent_at, scheduled_for=sent_at)


def send_due(at=NOON) -> int:
    with SessionLocal() as db:
        return notifications.send_due(db, at)


def schedule_due(at=NOON) -> int:
    with SessionLocal() as db:
        added = notifications.schedule_due(db, at)
        db.commit()
        return added


def load(model, row_id):
    with SessionLocal() as db:
        return db.get(model, uuid.UUID(str(row_id)))


def rows(model, **filters):
    with SessionLocal() as db:
        query = select(model).where(*(getattr(model, name) == value for name, value in filters.items()))
        return db.scalars(query).all()


def set_settings(user_id, **fields):
    with SessionLocal() as db:
        prefs = db.get(UserSettings, uuid.UUID(user_id))
        for field, value in fields.items():
            setattr(prefs, field, value)
        db.commit()


def outcome(row_id) -> tuple[str, str | None]:
    row = load(Notification, row_id)
    return row.status, row.skip_reason


def test_web_key_needs_configuration(client, signed_in, monkeypatch):
    missing = client.get("/v1/push/web-key", headers=signed_in.headers)
    assert missing.status_code == 503 and missing.json()["error"]["code"] == "push_not_configured"
    monkeypatch.setattr(settings, "vapid_public_key", "BPublicKey")
    assert client.get("/v1/push/web-key", headers=signed_in.headers).json() == {"vapid_public_key": "BPublicKey"}
    assert client.get("/v1/push/web-key").status_code == 401


def test_register_update_list_and_delete_devices(client, signed_in):
    headers = signed_in.headers
    web = register(client, headers)
    assert web == {"id": web["id"], "platform": "web", "name": "Chrome on Mac", "enabled": True, "created_at": web["created_at"]}
    assert web["created_at"].endswith("Z")

    again = register(client, headers, {**WEB, "name": "Chrome on the laptop"})
    assert again["id"] == web["id"] and again["name"] == "Chrome on the laptop"
    phone = register(client, headers, IOS)
    assert phone["platform"] == "ios" and register(client, headers, IOS)["id"] == phone["id"]

    listed = client.get("/v1/push/devices", headers=headers).json()["items"]
    assert [item["id"] for item in listed] == [web["id"], phone["id"]]
    assert listed[0] == {**again, "last_sent_at": None}
    with SessionLocal() as db:
        stored = db.get(PushDevice, uuid.UUID(phone["id"]))
        assert (stored.apns_token, stored.apns_environment, stored.web_endpoint) == ("a1b2c3d4e5f6", "sandbox", None)

    for bad in (
        {"platform": "web", "name": "no subscription"},
        {"platform": "web", "subscription": {"endpoint": "http://push.test/plain", "keys": {"p256dh": "k", "auth": "a"}}},
        {"platform": "ios", "environment": "production"},
        {"platform": "ios", "apns_token": "a1b2c3d4e5f6"},
        {"platform": "ios", "apns_token": "not-hex!", "environment": "production"},
    ):
        reply = client.post("/v1/push/devices", json=bad, headers=headers)
        assert reply.status_code == 400 and reply.json()["error"]["code"] == "invalid_subscription", bad
    assert client.post("/v1/push/devices", json={**WEB, "platform": "android"}, headers=headers).status_code == 400
    assert client.post("/v1/push/devices", json={**WEB, "extra": 1}, headers=headers).status_code == 400

    assert client.delete(f"/v1/push/devices/{web['id']}", headers=headers).status_code == 204
    assert client.delete(f"/v1/push/devices/{web['id']}", headers=headers).status_code == 404
    assert [item["id"] for item in client.get("/v1/push/devices", headers=headers).json()["items"]] == [phone["id"]]


def test_a_known_endpoint_moves_to_the_user_signed_in_now(client, fake_provider, signed_in):
    first = register(client, signed_in.headers)
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com", given_name="Bob").json())
    assert client.delete(f"/v1/push/devices/{first['id']}", headers=other).status_code == 404
    assert client.post(f"/v1/push/devices/{first['id']}/test", headers=other).status_code == 404
    moved = register(client, other)
    assert moved["id"] == first["id"]
    assert client.get("/v1/push/devices", headers=signed_in.headers).json()["items"] == []
    assert [item["id"] for item in client.get("/v1/push/devices", headers=other).json()["items"]] == [first["id"]]


def test_test_send_goes_to_that_device(client, signed_in, fake_push):
    headers = signed_in.headers
    device = register(client, headers, IOS)
    reply = client.post(f"/v1/push/devices/{device['id']}/test", headers=headers)
    assert reply.status_code == 202, reply.text
    assert reply.json() == {"sent": True, "error": None}
    ((platform, device_id, payload),) = fake_push.calls
    assert platform == "ios" and str(device_id) == device["id"]
    assert payload["title"] == "Rumi" and payload["body"] == "Notifications are on" and payload["link"] == "/today"
    uuid.UUID(payload["id"])
    assert client.get("/v1/push/devices", headers=headers).json()["items"][0]["last_sent_at"].endswith("Z")

    fake_push.fail = push_send.SendError("APNS_BUNDLE_ID is not set")
    failed = client.post(f"/v1/push/devices/{device['id']}/test", headers=headers)
    assert failed.status_code == 202 and failed.json() == {"sent": False, "error": "APNS_BUNDLE_ID is not set"}

    fake_push.fail = push_send.DeadDevice("apns returned 410")
    assert client.post(f"/v1/push/devices/{device['id']}/test", headers=headers).status_code == 202
    assert client.get("/v1/push/devices", headers=headers).json()["items"][0]["enabled"] is False
    refused = client.post(f"/v1/push/devices/{device['id']}/test", headers=headers)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "device_disabled"


def test_send_due_delivers_to_every_enabled_device(client, signed_in, fake_push):
    headers = signed_in.headers
    user_id = signed_in.user["id"]
    web = register(client, headers)
    phone = register(client, headers, IOS)
    row_id = add_row(user_id)
    assert send_due() == 1
    assert outcome(row_id) == ("sent", None)
    assert load(Notification, row_id).sent_at == NOON
    assert sorted((platform, str(device_id)) for platform, device_id, _ in fake_push.calls) == sorted([("web", web["id"]), ("ios", phone["id"])])
    payload = fake_push.calls[0][2]
    assert payload == {"id": str(row_id), "title": "Rumi", "body": "How did the walk go?", "link": "/chat", "category": "check_ins"}
    deliveries = rows(NotificationDelivery, notification_id=row_id)
    assert sorted((d.status, d.error, d.sent_at) for d in deliveries) == [("sent", None, NOON), ("sent", None, NOON)]
    assert load(PushDevice, web["id"]).last_sent_at == NOON
    assert send_due() == 0 and len(fake_push.calls) == 2


def test_rules_skip_with_a_reason(client, signed_in, fake_push):
    headers = signed_in.headers
    user_id = signed_in.user["id"]
    assert outcome(add_row(user_id)) == ("scheduled", None)
    send_due()
    assert outcome(rows(Notification)[0].id) == ("skipped", "no_device")

    register(client, headers)
    set_settings(user_id, notification_categories={"check_ins": False})
    row_id = add_row(user_id)
    send_due()
    assert outcome(row_id) == ("skipped", "category_off")

    set_settings(user_id, notification_categories={}, push_enabled=False)
    row_id = add_row(user_id)
    send_due()
    assert outcome(row_id) == ("skipped", "category_off")

    set_settings(user_id, push_enabled=True, ai_paused=True)
    row_id = add_row(user_id)
    send_due()
    assert outcome(row_id) == ("skipped", "paused")

    set_settings(user_id, ai_paused=False)
    habit = add_habit(client, headers)
    row_id = add_row(user_id, source="habit", source_id=uuid.UUID(habit["id"]), category="habit_moments")
    client.patch(f"/v1/habits/{habit['id']}", json={"paused": True}, headers=headers)
    send_due()
    assert outcome(row_id) == ("skipped", "paused")

    visit = add_appointment(client, headers, NOON + timedelta(hours=2))
    row_id = add_row(user_id, source="visit", source_id=uuid.UUID(visit["id"]), category="logistics")
    client.patch(f"/v1/appointments/{visit['id']}", json={"status": "cancelled"}, headers=headers)
    send_due()
    assert outcome(row_id) == ("skipped", "stale")

    future = client.get("/v1/notifications", headers=headers).json()["items"]
    assert fake_push.calls == [] and all(item["status"] == "skipped" for item in future)


def test_quiet_hours_move_a_reminder_and_skip_a_nudge(client, signed_in, fake_push):
    headers = signed_in.headers
    user_id = signed_in.user["id"]
    register(client, headers)
    client.patch("/v1/me/profile", json={"timezone": "America/New_York"}, headers=headers)
    habit = add_habit(client, headers)
    # 03:00 UTC on July 3 is 23:00 on July 2 in New York, inside the default 21:00 to 08:00 quiet hours.
    late = datetime(2026, 7, 3, 3, 0, tzinfo=UTC)
    reminder = add_row(user_id, source="habit", source_id=uuid.UUID(habit["id"]), category="habit_moments", scheduled_for=late)
    nudge = add_row(user_id, scheduled_for=late)
    assert send_due(late) == 2
    assert outcome(nudge) == ("skipped", "quiet_hours")
    assert outcome(reminder) == ("scheduled", None)
    assert load(Notification, reminder).scheduled_for == datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    assert fake_push.calls == []

    assert send_due(datetime(2026, 7, 3, 11, 59, tzinfo=UTC)) == 0
    assert send_due(datetime(2026, 7, 3, 12, 0, tzinfo=UTC)) == 1
    assert outcome(reminder) == ("sent", None)

    # Quiet hours that do not cross midnight, and a day with none at all.
    set_settings(user_id, quiet_start=13, quiet_end=15)
    afternoon = add_row(user_id, scheduled_for=datetime(2026, 7, 3, 18, 0, tzinfo=UTC))
    send_due(datetime(2026, 7, 3, 18, 0, tzinfo=UTC))
    assert outcome(afternoon) == ("skipped", "quiet_hours")
    set_settings(user_id, quiet_start=8, quiet_end=8)
    always = add_row(user_id, scheduled_for=datetime(2026, 7, 3, 18, 0, tzinfo=UTC))
    send_due(datetime(2026, 7, 3, 18, 0, tzinfo=UTC))
    assert outcome(always) == ("sent", None)


def test_daily_and_weekly_limits_spare_visit_reminders(client, signed_in, fake_push):
    headers = signed_in.headers
    user_id = signed_in.user["id"]
    register(client, headers)
    add_sent(user_id, NOON - timedelta(hours=1), count=2)
    nudge = add_row(user_id)
    visit = add_appointment(client, headers, NOON + timedelta(hours=2))
    reminder = add_row(user_id, source="visit", source_id=uuid.UUID(visit["id"]), category="logistics")
    assert send_due() == 2
    assert outcome(nudge) == ("skipped", "daily_limit")
    assert outcome(reminder) == ("sent", None)

    # Wednesday of the same week holds eight sends, so Friday is under the daily limit but over the weekly one.
    tomorrow = NOON + timedelta(days=1)
    add_sent(user_id, NOON - timedelta(days=2), count=8)
    add_sent(user_id, NOON - timedelta(days=2), count=3, source="visit")
    weekly = add_row(user_id, scheduled_for=tomorrow)
    assert send_due(tomorrow) == 1
    assert outcome(weekly) == ("skipped", "weekly_limit")

    # Monday starts a new week.
    monday = NOON + timedelta(days=3)
    fresh = add_row(user_id, scheduled_for=monday)
    send_due(monday)
    assert outcome(fresh) == ("sent", None)


def test_dead_devices_are_turned_off(client, signed_in, fake_push):
    headers = signed_in.headers
    user_id = signed_in.user["id"]
    web = register(client, headers)
    phone = register(client, headers, IOS)

    fake_push.fail = push_send.DeadDevice("web push returned 410")
    row_id = add_row(user_id)
    send_due()
    assert outcome(row_id) == ("failed", None)
    assert load(PushDevice, web["id"]).enabled is False and load(PushDevice, phone["id"]).enabled is False
    assert sorted(d.error for d in rows(NotificationDelivery, notification_id=row_id)) == ["web push returned 410"] * 2

    register(client, headers, IOS)
    fake_push.fail = push_send.SendError("apns returned 500: busy")
    for attempt in range(1, notifications.MAX_FAILURES + 1):
        send_due()
        row_id = add_row(user_id, scheduled_for=NOON - timedelta(minutes=attempt))
        send_due()
        device = load(PushDevice, phone["id"])
        assert device.failure_count == attempt and device.enabled is (attempt < notifications.MAX_FAILURES)
    assert outcome(row_id) == ("failed", None)
    no_device = add_row(user_id)
    assert outcome(no_device) == ("scheduled", None)
    send_due()
    assert outcome(no_device) == ("skipped", "no_device")

    # One good send clears the count.
    register(client, headers, IOS)
    fake_push.fail = None
    row_id = add_row(user_id)
    send_due()
    assert outcome(row_id) == ("sent", None) and load(PushDevice, phone["id"]).failure_count == 0


def test_schedule_due_adds_each_reminder_once(client, signed_in):
    headers = signed_in.headers
    client.patch("/v1/me/profile", json={"timezone": "America/New_York"}, headers=headers)
    evening = add_habit(client, headers, reminder_time="19:00")
    add_habit(client, headers, reminder_time="07:00")
    add_habit(client, headers)
    assert schedule_due() == 1
    assert schedule_due() == 0
    (row,) = rows(Notification)
    assert (row.source, str(row.source_id), row.category, row.body, row.link) == ("habit", evening["id"], "habit_moments", "Time for: 10-minute walk", "/today")
    assert row.scheduled_for == datetime(2026, 7, 3, 23, 0, tzinfo=UTC)
    assert row.idempotency_key == f"habit:{evening['id']}:2026-07-03"

    client.patch(f"/v1/habits/{evening['id']}", json={"reminder_time": "20:00"}, headers=headers)
    assert schedule_due() == 0
    assert load(Notification, row.id).scheduled_for == datetime(2026, 7, 4, 0, 0, tzinfo=UTC)
    assert schedule_due(NOON + timedelta(days=1)) == 1
    assert len(rows(Notification)) == 2

    client.patch(f"/v1/habits/{evening['id']}", json={"paused": True}, headers=headers)
    assert schedule_due(NOON + timedelta(days=2)) == 0


def test_schedule_due_adds_visit_reminders_and_follows_a_reschedule(client, signed_in, fake_push):
    headers = signed_in.headers
    client.patch("/v1/me/profile", json={"timezone": "America/New_York"}, headers=headers)
    starts = datetime(2026, 7, 6, 14, 0, tzinfo=UTC)
    visit = add_appointment(client, headers, starts)
    add_appointment(client, headers, starts, status="cancelled")
    add_appointment(client, headers, NOON + timedelta(hours=1))
    assert schedule_due() == 3
    assert schedule_due() == 0
    found = {row.idempotency_key: row for row in rows(Notification)}
    assert set(found) == {f"visit:{visit['id']}:1d", f"visit:{visit['id']}:2h", f"visit_prep:{visit['id']}:2d"}
    assert (found[f"visit:{visit['id']}:1d"].body, found[f"visit:{visit['id']}:1d"].scheduled_for) == ("Visit tomorrow at 10:00", starts - timedelta(days=1))
    assert (found[f"visit:{visit['id']}:2h"].body, found[f"visit:{visit['id']}:2h"].scheduled_for) == ("Visit today at 10:00", starts - timedelta(hours=2))
    prep = found[f"visit_prep:{visit['id']}:2d"]
    assert (prep.body, prep.link, prep.scheduled_for, prep.category) == ("Get ready for your visit", f"/visits/{visit['id']}/prep", starts - timedelta(days=2), "logistics")
    assert all(row.link.startswith(f"/visits/{visit['id']}") and row.user_id == uuid.UUID(signed_in.user["id"]) for row in found.values())

    moved = starts + timedelta(hours=1)
    client.patch(f"/v1/appointments/{visit['id']}", json={"starts_at": moved.isoformat(), "ends_at": (moved + timedelta(hours=1)).isoformat()}, headers=headers)
    assert schedule_due() == 0
    found = {row.idempotency_key: row for row in rows(Notification)}
    assert (found[f"visit:{visit['id']}:1d"].body, found[f"visit:{visit['id']}:1d"].scheduled_for) == ("Visit tomorrow at 11:00", moved - timedelta(days=1))
    assert found[f"visit_prep:{visit['id']}:2d"].scheduled_for == moved - timedelta(days=2)

    # A reviewed prep gets no new prep reminder, and a reminder that is already there is skipped when its time comes.
    register(client, headers)
    client.post(f"/v1/appointments/{visit['id']}/prep/review", headers=headers)
    assert schedule_due() == 0
    send_due(moved - timedelta(days=2))
    assert outcome(prep.id) == ("skipped", "stale")
    send_due(moved - timedelta(days=1))
    assert outcome(found[f"visit:{visit['id']}:1d"].id) == ("sent", None)
    assert fake_push.calls[0][2]["body"] == "Visit tomorrow at 11:00"


def test_chat_server_nudge_webhook_checks_the_secret_and_the_key(client, signed_in, fake_push, hook_secret, monkeypatch):
    user_id = signed_in.user["id"]
    body = {**NUDGE, "person_id": user_id}
    assert client.post("/v1/integrations/chat-server/nudge", json=body).status_code == 401
    wrong = client.post("/v1/integrations/chat-server/nudge", json=body, headers={"X-Rumi-Webhook-Secret": "nope"})
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "webhook_secret_invalid"
    assert client.post("/v1/integrations/chat-server/nudge", json=body, headers=signed_in.headers).status_code == 401

    accepted = client.post("/v1/integrations/chat-server/nudge", json=body, headers=HOOK)
    assert accepted.status_code == 202, accepted.text
    again = client.post("/v1/integrations/chat-server/nudge", json={**body, "content": "changed"}, headers=HOOK)
    assert again.status_code == 202 and again.json() == accepted.json()
    (row,) = rows(Notification)
    assert (row.source, row.category, row.body, row.link, row.status) == ("chat_nudge", "check_ins", "How did the walk go?", "/chat", "scheduled")
    assert row.idempotency_key == "chat_nudge:nudge-1" and row.scheduled_for <= datetime.now(UTC)

    other = client.post("/v1/integrations/chat-server/nudge", json={**body, "idempotency_key": "nudge-2"}, headers=HOOK)
    assert other.status_code == 202 and other.json() != accepted.json()
    unknown = client.post("/v1/integrations/chat-server/nudge", json={**body, "person_id": str(uuid.uuid4())}, headers=HOOK)
    assert unknown.status_code == 404
    assert client.post("/v1/integrations/chat-server/nudge", json={**body, "content": ""}, headers=HOOK).status_code == 400
    assert client.post("/v1/integrations/chat-server/nudge", json={**body, "extra": 1}, headers=HOOK).status_code == 400

    monkeypatch.setattr(settings, "chat_server_webhook_secret", "")
    assert client.post("/v1/integrations/chat-server/nudge", json=body, headers={"X-Rumi-Webhook-Secret": ""}).status_code == 401

    register(client, signed_in.headers)
    set_settings(user_id, quiet_start=0, quiet_end=0)
    with SessionLocal() as db:
        assert notifications.send_due(db, datetime.now(UTC) + timedelta(seconds=1)) == 2
    assert [call[2]["body"] for call in fake_push.calls] == ["How did the walk go?"] * 2


def test_notifications_list_and_opened(client, fake_provider, signed_in):
    headers = signed_in.headers
    user_id = signed_in.user["id"]
    assert client.get("/v1/notifications", headers=headers).json() == {"items": [], "next_cursor": None}
    sent = add_row(user_id, status="sent", sent_at=NOON, scheduled_for=NOON)
    skipped = add_row(user_id, status="skipped", skip_reason="no_device", scheduled_for=NOON - timedelta(hours=1))
    add_row(user_id, scheduled_for=NOON + timedelta(days=1))

    page = client.get("/v1/notifications?limit=1", headers=headers).json()
    assert page["items"] == [
        {
            "id": str(sent),
            "category": "check_ins",
            "body": "How did the walk go?",
            "link": "/chat",
            "status": "sent",
            "skip_reason": None,
            "sent_at": "2026-07-03T16:00:00Z",
            "opened_at": None,
        }
    ]
    rest = client.get(f"/v1/notifications?limit=1&cursor={page['next_cursor']}", headers=headers).json()
    assert [item["id"] for item in rest["items"]] == [str(skipped)] and rest["next_cursor"] is None
    assert rest["items"][0]["skip_reason"] == "no_device" and rest["items"][0]["sent_at"] is None
    assert client.get("/v1/notifications?cursor=garbage", headers=headers).status_code == 400

    assert client.post(f"/v1/notifications/{sent}/opened", headers=headers).status_code == 204
    first = load(Notification, sent).opened_at
    assert first is not None
    assert client.post(f"/v1/notifications/{sent}/opened", headers=headers).status_code == 204
    assert load(Notification, sent).opened_at == first
    assert client.get("/v1/notifications", headers=headers).json()["items"][0]["opened_at"].endswith("Z")
    assert client.post(f"/v1/notifications/{uuid.uuid4()}/opened", headers=headers).status_code == 404

    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com", given_name="Bob").json())
    assert client.get("/v1/notifications", headers=other).json()["items"] == []
    assert client.post(f"/v1/notifications/{sent}/opened", headers=other).status_code == 404
    assert client.get("/v1/notifications").status_code == 401


def test_senders_report_missing_settings_and_apns_answers(client, signed_in, monkeypatch):
    headers = signed_in.headers
    user_id = signed_in.user["id"]
    web = register(client, headers)
    phone = register(client, headers, IOS)
    row_id = add_row(user_id)
    send_due()
    assert outcome(row_id) == ("failed", None)
    errors = {str(d.device_id): d.error for d in rows(NotificationDelivery, notification_id=row_id)}
    assert errors[web["id"]] == "VAPID_PRIVATE_KEY or VAPID_SUBJECT is not set"
    assert errors[phone["id"]] == "APNS_BUNDLE_ID is not set"

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    monkeypatch.setattr(settings, "apns_bundle_id", "com.example.rumi")
    monkeypatch.setattr(settings, "apns_key_id", "KEY123")
    monkeypatch.setattr(settings, "apns_team_id", "TEAM123")
    monkeypatch.setattr(settings, "apns_private_key", pem.decode().replace("\n", "\\n"))
    monkeypatch.setattr(push_send, "_apns_token", None)
    apns = SimpleNamespace(requests=[], status=200)

    def handler(request):
        apns.requests.append(request)
        return httpx.Response(apns.status, json={"reason": "Unregistered"} if apns.status != 200 else None)

    monkeypatch.setattr(push_send, "client", httpx.Client(transport=httpx.MockTransport(handler)))
    client.delete(f"/v1/push/devices/{web['id']}", headers=headers)
    row_id = add_row(user_id, scheduled_for=NOON - timedelta(minutes=2))
    send_due()
    assert outcome(row_id) == ("sent", None)
    (request,) = apns.requests
    assert request.url == f"https://api.sandbox.push.apple.com/3/device/{IOS['apns_token']}"
    assert request.headers["apns-topic"] == "com.example.rumi" and request.headers["authorization"].startswith("bearer ")
    sent = json.loads(request.content)
    assert sent["aps"] == {"alert": {"title": "Rumi", "body": "How did the walk go?"}, "sound": "default", "thread-id": "check_ins"}
    assert sent["id"] == str(row_id) and sent["link"] == "/chat"

    apns.status = 410
    row_id = add_row(user_id, scheduled_for=NOON - timedelta(minutes=3))
    send_due()
    assert outcome(row_id) == ("failed", None) and load(PushDevice, phone["id"]).enabled is False
    (delivery,) = rows(NotificationDelivery, notification_id=row_id)
    assert delivery.error == "apns returned 410"
