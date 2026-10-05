import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.clock import now
from app.db import SessionLocal
from app.models import Habit, HabitCheckIn
from tests.conftest import bearer, sign_in


def add_journey(client, headers, **fields):
    body = {"title": "Keep my A1c steady", "why": "I want to keep up with my grandkids", **fields}
    reply = client.post("/v1/journeys", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def add_habit(client, headers, journey_id, **fields):
    reply = client.post(f"/v1/journeys/{journey_id}/habits", json={"title": "10-minute walk", **fields}, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def set_timezone(client, headers, name):
    assert client.patch("/v1/me/profile", json={"timezone": name}, headers=headers).status_code == 200


def today_in(name) -> date:
    return now().astimezone(ZoneInfo(name)).date()


def check_in(client, headers, habit_id, day, outcome="kept", note=""):
    return client.put(f"/v1/habits/{habit_id}/check-ins/{day.isoformat()}", json={"outcome": outcome, "note": note}, headers=headers)


def today_ids(client, headers) -> list[str]:
    return [item["habit_id"] for item in client.get("/v1/habits/today", headers=headers).json()["items"]]


def test_start_a_journey_then_list_edit_and_delete_it(client, signed_in):
    headers = signed_in.headers
    assert client.get("/v1/journeys", headers=headers).json() == {"items": []}
    journey = add_journey(client, headers)
    assert journey == {
        "id": journey["id"],
        "title": "Keep my A1c steady",
        "why": "I want to keep up with my grandkids",
        "plan_goal_id": None,
        "status": "active",
        "habits": [],
    }
    second = add_journey(client, headers, title="Sleep by eleven", why="")
    assert [item["id"] for item in client.get("/v1/journeys", headers=headers).json()["items"]] == [journey["id"], second["id"]]
    assert client.get(f"/v1/journeys/{journey['id']}", headers=headers).json() == journey

    assert client.post("/v1/journeys", json={"why": "no title"}, headers=headers).status_code == 400
    assert client.post("/v1/journeys", json={"title": "x", "pace": "steady"}, headers=headers).status_code == 400
    unknown_goal = client.post("/v1/journeys", json={"title": "x", "plan_goal_id": str(uuid.uuid4())}, headers=headers)
    assert unknown_goal.status_code == 404 and unknown_goal.json()["error"]["code"] == "not_found"

    edited = client.patch(f"/v1/journeys/{journey['id']}", json={"title": "Keep my A1c under 7", "status": "paused"}, headers=headers)
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Keep my A1c under 7" and edited.json()["status"] == "paused"
    assert edited.json()["why"] == "I want to keep up with my grandkids"
    assert [item["id"] for item in client.get("/v1/journeys", headers=headers).json()["items"]] == [second["id"]]
    assert [item["id"] for item in client.get("/v1/journeys?status=paused", headers=headers).json()["items"]] == [journey["id"]]
    assert len(client.get("/v1/journeys?status=all", headers=headers).json()["items"]) == 2
    assert client.get("/v1/journeys?status=finished", headers=headers).status_code == 400
    assert client.patch(f"/v1/journeys/{journey['id']}", json={"status": "archived"}, headers=headers).status_code == 400
    assert client.patch(f"/v1/journeys/{journey['id']}", json={"title": ""}, headers=headers).status_code == 400

    assert client.delete(f"/v1/journeys/{journey['id']}", headers=headers).status_code == 204
    missing = client.get(f"/v1/journeys/{journey['id']}", headers=headers)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert client.delete(f"/v1/journeys/{journey['id']}", headers=headers).status_code == 404
    assert client.post(f"/v1/journeys/{journey['id']}/habits", json={"title": "x"}, headers=headers).status_code == 404


def test_add_and_edit_a_habit_with_its_support_plan(client, signed_in):
    headers = signed_in.headers
    journey = add_journey(client, headers)
    full = {
        "title": "10-minute walk",
        "context": "After lunch",
        "reason": "Walking helps my numbers",
        "cue": "When I put my lunch plate away",
        "barrier": "Rain",
        "fallback": "Walk inside for 5 minutes",
        "confidence": 3,
        "pace": "small_steps",
        "reminder_time": "12:45",
        "origin": "rumi_suggestion",
    }
    habit = add_habit(client, headers, journey["id"], **full)
    assert habit == {**full, "id": habit["id"], "journey_id": journey["id"], "paused": False, "updated_at": habit["updated_at"]}
    assert habit["updated_at"].endswith("Z")

    bare = add_habit(client, headers, journey["id"], title="Water with breakfast")
    assert bare["context"] is None and bare["confidence"] is None and bare["reminder_time"] is None
    assert bare["pace"] == "small_steps" and bare["origin"] == "patient" and bare["paused"] is False

    url = f"/v1/journeys/{journey['id']}/habits"
    assert client.post(url, json={"context": "no title"}, headers=headers).status_code == 400
    assert client.post(url, json={"title": "x", "reminder_time": "25:99"}, headers=headers).status_code == 400
    assert client.post(url, json={"title": "x", "confidence": 6}, headers=headers).status_code == 400
    assert client.post(url, json={"title": "x", "pace": "fast"}, headers=headers).status_code == 400
    assert client.post(url, json={"title": "x", "origin": "doctor"}, headers=headers).status_code == 400
    assert client.post(url, json={"title": "x", "paused": True}, headers=headers).status_code == 400

    edited = client.patch(
        f"/v1/habits/{habit['id']}", json={"fallback": "Walk to the mailbox", "confidence": 4, "context": None, "reminder_time": "07:30:00"}, headers=headers
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["fallback"] == "Walk to the mailbox" and edited.json()["confidence"] == 4
    assert edited.json()["context"] is None and edited.json()["reminder_time"] == "07:30"
    assert edited.json()["cue"] == "When I put my lunch plate away"
    assert client.patch(f"/v1/habits/{habit['id']}", json={"title": None}, headers=headers).status_code == 400
    assert client.patch(f"/v1/habits/{habit['id']}", json={"pace": None}, headers=headers).status_code == 400
    assert client.patch(f"/v1/habits/{habit['id']}", json={"streak": 3}, headers=headers).status_code == 400
    assert client.patch(f"/v1/habits/{uuid.uuid4()}", json={"title": "x"}, headers=headers).status_code == 404

    detail = client.get(f"/v1/journeys/{journey['id']}", headers=headers).json()
    assert [item["id"] for item in detail["habits"]] == [habit["id"], bare["id"]]
    assert detail["habits"][0] == {**edited.json(), "this_week": []}
    (listed,) = client.get("/v1/journeys", headers=headers).json()["items"]
    assert listed["habits"][0] == {"id": habit["id"], "title": "10-minute walk", "context": None, "paused": False, "this_week": []}


def test_check_ins_use_the_patients_local_date_and_replace_or_undo(client, signed_in):
    headers = signed_in.headers
    set_timezone(client, headers, "Pacific/Kiritimati")
    journey = add_journey(client, headers)
    habit = add_habit(client, headers, journey["id"], fallback="Walk inside for 5 minutes")
    today = today_in("Pacific/Kiritimati")
    url = f"/v1/habits/{habit['id']}/check-ins"

    future = check_in(client, headers, habit["id"], today + timedelta(days=1))
    assert future.status_code == 400 and future.json()["error"]["code"] == "invalid_date"

    kept = check_in(client, headers, habit["id"], today, note="")
    assert kept.status_code == 200, kept.text
    assert kept.json() == {"date": today.isoformat(), "outcome": "kept", "note": ""}
    screen = client.get("/v1/habits/today", headers=headers).json()
    assert screen["date"] == today.isoformat()
    assert screen["items"] == [
        {
            "habit_id": habit["id"],
            "title": "10-minute walk",
            "context": None,
            "fallback": "Walk inside for 5 minutes",
            "reminder_time": None,
            "check_in": {"outcome": "kept", "note": ""},
        }
    ]

    # A second check-in on the same day replaces the first, and the snapshot keeps the plan as it was.
    replaced = check_in(client, headers, habit["id"], today, outcome="fallback", note="Rained, walked inside")
    assert replaced.status_code == 200 and replaced.json()["outcome"] == "fallback"
    assert client.get(url, headers=headers).json()["items"] == [{"date": today.isoformat(), "outcome": "fallback", "note": "Rained, walked inside"}]
    assert client.patch(f"/v1/habits/{habit['id']}", json={"fallback": "Walk to the mailbox"}, headers=headers).status_code == 200
    with SessionLocal() as db:
        (row,) = db.scalars(select(HabitCheckIn)).all()
        assert row.plan_snapshot["fallback"] == "Walk inside for 5 minutes" and row.plan_snapshot["title"] == "10-minute walk"

    yesterday = today - timedelta(days=1)
    assert check_in(client, headers, habit["id"], yesterday, outcome="skipped").status_code == 200
    assert [item["date"] for item in client.get(url, headers=headers).json()["items"]] == [yesterday.isoformat(), today.isoformat()]
    assert [item["date"] for item in client.get(f"{url}?from={today}", headers=headers).json()["items"]] == [today.isoformat()]
    assert [item["date"] for item in client.get(f"{url}?to={yesterday}", headers=headers).json()["items"]] == [yesterday.isoformat()]

    assert client.delete(f"{url}/{today.isoformat()}", headers=headers).status_code == 204
    assert client.get("/v1/habits/today", headers=headers).json()["items"][0]["check_in"] is None
    gone = client.delete(f"{url}/{today.isoformat()}", headers=headers)
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "not_found"

    assert client.put(f"{url}/2026-13-01", json={"outcome": "kept"}, headers=headers).status_code == 400
    assert client.put(f"{url}/{today.isoformat()}", json={"outcome": "nailed_it"}, headers=headers).status_code == 400
    assert client.put(f"{url}/{today.isoformat()}", json={"outcome": "kept", "mood": 5}, headers=headers).status_code == 400
    assert client.put(f"/v1/habits/{uuid.uuid4()}/check-ins/{today.isoformat()}", json={"outcome": "kept"}, headers=headers).status_code == 404

    # Today follows the profile timezone. These two zones are 25 hours apart.
    set_timezone(client, headers, "Pacific/Pago_Pago")
    assert client.get("/v1/habits/today", headers=headers).json()["date"] == today_in("Pacific/Pago_Pago").isoformat()


def test_this_week_starts_on_monday_in_the_patients_timezone(client, signed_in):
    headers = signed_in.headers
    set_timezone(client, headers, "America/New_York")
    journey = add_journey(client, headers)
    habit = add_habit(client, headers, journey["id"])
    today = today_in("America/New_York")
    monday = today - timedelta(days=today.weekday())
    sunday = monday - timedelta(days=1)
    assert check_in(client, headers, habit["id"], sunday, outcome="blocked").status_code == 200
    assert check_in(client, headers, habit["id"], monday, outcome="kept").status_code == 200
    if today != monday:
        assert check_in(client, headers, habit["id"], today, outcome="fallback").status_code == 200

    expected = [{"date": monday.isoformat(), "outcome": "kept"}]
    if today != monday:
        expected.append({"date": today.isoformat(), "outcome": "fallback"})
    (listed,) = client.get("/v1/journeys", headers=headers).json()["items"]
    assert listed["habits"][0]["this_week"] == expected
    assert client.get(f"/v1/journeys/{journey['id']}", headers=headers).json()["habits"][0]["this_week"] == expected
    assert len(client.get(f"/v1/habits/{habit['id']}/check-ins", headers=headers).json()["items"]) == len(expected) + 1


def test_today_shows_only_live_habits_of_active_journeys(client, signed_in):
    headers = signed_in.headers
    walking = add_journey(client, headers)
    sleep = add_journey(client, headers, title="Sleep by eleven")
    late = add_habit(client, headers, walking["id"], title="Evening walk", reminder_time="19:00")
    early = add_habit(client, headers, walking["id"], title="Morning stretch", reminder_time="07:00")
    no_time = add_habit(client, headers, sleep["id"], title="Lights out")
    assert today_ids(client, headers) == [early["id"], late["id"], no_time["id"]]

    paused = client.patch(f"/v1/habits/{late['id']}", json={"paused": True}, headers=headers)
    assert paused.json()["paused"] is True
    assert today_ids(client, headers) == [early["id"], no_time["id"]]
    refused = check_in(client, headers, late["id"], today_in("UTC"))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "habit_paused"
    client.patch(f"/v1/habits/{late['id']}", json={"paused": False}, headers=headers)
    assert today_ids(client, headers) == [early["id"], late["id"], no_time["id"]]
    assert check_in(client, headers, late["id"], today_in("UTC")).status_code == 200

    # Pausing the journey pauses every habit in it. Resuming brings them back.
    paused_journey = client.patch(f"/v1/journeys/{walking['id']}", json={"status": "paused"}, headers=headers).json()
    assert [habit["paused"] for habit in paused_journey["habits"]] == [True, True]
    assert today_ids(client, headers) == [no_time["id"]]
    assert check_in(client, headers, early["id"], today_in("UTC")).status_code == 409
    resumed = client.patch(f"/v1/journeys/{walking['id']}", json={"status": "active"}, headers=headers).json()
    assert [habit["paused"] for habit in resumed["habits"]] == [False, False]
    assert today_ids(client, headers) == [early["id"], late["id"], no_time["id"]]

    client.patch(f"/v1/journeys/{sleep['id']}", json={"status": "done"}, headers=headers)
    assert today_ids(client, headers) == [early["id"], late["id"]]

    # A removed habit leaves every list but keeps its check-ins.
    assert client.delete(f"/v1/habits/{late['id']}", headers=headers).status_code == 204
    assert today_ids(client, headers) == [early["id"]]
    assert [habit["id"] for habit in client.get(f"/v1/journeys/{walking['id']}", headers=headers).json()["habits"]] == [early["id"]]
    assert client.get(f"/v1/habits/{late['id']}/check-ins", headers=headers).status_code == 404
    assert client.patch(f"/v1/habits/{late['id']}", json={"title": "x"}, headers=headers).status_code == 404
    assert client.delete(f"/v1/habits/{late['id']}", headers=headers).status_code == 404
    with SessionLocal() as db:
        assert db.get(Habit, uuid.UUID(late["id"])).deleted_at is not None
        assert db.scalar(select(HabitCheckIn).where(HabitCheckIn.habit_id == uuid.UUID(late["id"]))) is not None

    # Deleting the journey removes its habits and their check-ins for good.
    assert client.delete(f"/v1/journeys/{walking['id']}", headers=headers).status_code == 204
    with SessionLocal() as db:
        assert db.scalars(select(Habit).where(Habit.journey_id == uuid.UUID(walking["id"]))).all() == []
        assert db.scalars(select(HabitCheckIn)).all() == []


def test_users_only_see_their_own_journeys(client, fake_provider, signed_in):
    journey = add_journey(client, signed_in.headers)
    habit = add_habit(client, signed_in.headers, journey["id"])
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com", given_name="Bob").json())
    assert client.get("/v1/journeys", headers=other).json()["items"] == []
    assert client.get(f"/v1/journeys/{journey['id']}", headers=other).status_code == 404
    assert client.patch(f"/v1/habits/{habit['id']}", json={"title": "x"}, headers=other).status_code == 404
    assert check_in(client, other, habit["id"], today_in("UTC")).status_code == 404
    assert client.get("/v1/habits/today", headers=other).json()["items"] == []
    assert client.get("/v1/journeys").status_code == 401
    assert client.get("/v1/habits/today").status_code == 401
