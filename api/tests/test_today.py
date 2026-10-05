from datetime import timedelta
from zoneinfo import ZoneInfo

from app.clock import iso, now
from tests.test_me import complete_onboarding

ONBOARDING = {"kind": "onboarding", "title": "Finish setting up", "link": "/onboarding"}
CONSENT = {"kind": "consent", "title": "Turn on Rumi chat", "link": "/privacy"}


def add_appointment(client, headers, starts_at, **fields):
    body = {"kind": "video", "starts_at": starts_at.isoformat(), "ends_at": (starts_at + timedelta(hours=1)).isoformat(), **fields}
    reply = client.post("/v1/appointments", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def add_log(client, headers, kind, value, taken_at):
    reply = client.post("/v1/logs", json={"kind": kind, "value": value, "taken_at": taken_at.isoformat()}, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def today(client, headers) -> dict:
    reply = client.get("/v1/today", headers=headers)
    assert reply.status_code == 200, reply.text
    return reply.json()


def test_a_new_user_sees_an_empty_day_with_two_things_to_do(client, signed_in):
    assert today(client, signed_in.headers) == {
        "date": now().date().isoformat(),
        "next_visit": None,
        "latest": [],
        "habits_due": [],
        "needs_you": [ONBOARDING, CONSENT],
    }
    assert client.get("/v1/today").status_code == 401


def test_today_gathers_the_visit_the_latest_numbers_and_the_habits(client, signed_in, fake_chat_server):
    headers = signed_in.headers
    at = now()
    soon = add_appointment(client, headers, at + timedelta(days=3))
    add_appointment(client, headers, at + timedelta(days=1), status="cancelled")
    add_appointment(client, headers, at + timedelta(days=20))
    add_appointment(client, headers, at - timedelta(days=5))

    older = add_log(client, headers, "glucose", {"mg_dl": 110, "timing": "fasting"}, at - timedelta(days=2))
    add_log(client, headers, "glucose", {"mg_dl": 98, "timing": "fasting"}, at - timedelta(days=1))
    add_log(client, headers, "glucose", {"mg_dl": 140, "timing": "after_meal"}, at - timedelta(days=3))
    add_log(client, headers, "blood_pressure", {"systolic": 138, "diastolic": 84}, at - timedelta(hours=4))
    add_log(client, headers, "note", {"text": "Felt fine"}, at - timedelta(hours=1))
    newest_weight = add_log(client, headers, "weight", {"kg": 81.5}, at - timedelta(hours=2))
    assert client.delete(f"/v1/logs/{newest_weight['id']}", headers=headers).status_code == 204

    journey = client.post("/v1/journeys", json={"title": "Keep moving"}, headers=headers).json()
    habit = client.post(f"/v1/journeys/{journey['id']}/habits", json={"title": "10-minute walk", "fallback": "Stretch"}, headers=headers).json()

    screen = today(client, headers)
    assert screen["next_visit"] == {"id": soon["id"], "starts_at": soon["starts_at"], "prep_reviewed": False}
    assert screen["latest"] == [
        {"kind": "blood_pressure", "systolic": 138, "diastolic": 84, "taken_at": iso(at - timedelta(hours=4))},
        {"kind": "glucose", "mg_dl": 98, "timing": "fasting", "taken_at": iso(at - timedelta(days=1))},
    ]
    assert screen["habits_due"] == client.get("/v1/habits/today", headers=headers).json()["items"]
    assert [item["habit_id"] for item in screen["habits_due"]] == [habit["id"]]
    assert screen["needs_you"] == [{"kind": "visit_prep", "title": "Get ready for your visit", "link": f"/visits/{soon['id']}/prep"}, ONBOARDING, CONSENT]

    # Editing the older glucose log to a newer time makes it the latest one.
    client.patch(f"/v1/logs/{older['id']}", json={"taken_at": at.isoformat()}, headers=headers)
    assert today(client, headers)["latest"][1]["mg_dl"] == 110

    complete_onboarding(client, headers)
    assert today(client, headers)["needs_you"] == [{"kind": "visit_prep", "title": "Get ready for your visit", "link": f"/visits/{soon['id']}/prep"}, CONSENT]
    assert today(client, headers)["date"] == now().astimezone(ZoneInfo("America/New_York")).date().isoformat()

    client.put("/v1/me/consents/ai_chat", json={"granted": True, "policy_version": "2026-09"}, headers=headers)
    client.post(f"/v1/appointments/{soon['id']}/prep/review", headers=headers)
    screen = today(client, headers)
    assert screen["needs_you"] == [] and screen["next_visit"]["prep_reviewed"] is True

    # A visit more than seven days out is the next visit but is not yet something to do.
    client.patch(f"/v1/appointments/{soon['id']}", json={"status": "cancelled"}, headers=headers)
    screen = today(client, headers)
    assert screen["next_visit"]["prep_reviewed"] is False and screen["needs_you"] == []
    assert screen["next_visit"]["starts_at"] == iso(at + timedelta(days=20))
