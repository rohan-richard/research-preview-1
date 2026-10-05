import uuid

import pytest
from pydantic import ValidationError

from app.care_plans import import_care_plan
from app.db import SessionLocal
from tests.conftest import bearer, sign_in

DIABETES_PLAN = {
    "title": "Diabetes care plan",
    "description": "Keep A1c and blood pressure in range.",
    "status": "active",
    "period_start": "2026-04-01",
    "period_end": None,
    "author": "Dr. A. Patel",
    "organization": "Example Health",
    "fhir_resource_id": str(uuid.uuid4()),
    "goals": [
        {"description": "Keep A1c below 7%", "target_code": "4548-4", "target_value": 7.0, "target_unit": "%", "due_date": "2027-03-31"},
        {"description": "Walk after dinner most evenings", "status": "proposed"},
    ],
    "activities": [
        {"kind": "lab", "description": "A1c test every 3 months", "status": "scheduled", "scheduled_for": "2026-12-15"},
        {"kind": "education", "description": "Diabetes nutrition class"},
    ],
}


def import_plan(user_id: str, **overrides) -> dict:
    with SessionLocal() as db:
        plan = import_care_plan(db, uuid.UUID(user_id), {**DIABETES_PLAN, **overrides})
        db.commit()
        goals = {goal.description: str(goal.id) for goal in plan.goals}
        return {"id": str(plan.id), "goals": goals}


def ids(reply) -> list[str]:
    return [item["id"] for item in reply.json()["items"]]


def test_list_shows_active_plans_first_and_filters_by_status(client, signed_in):
    headers = signed_in.headers
    assert client.get("/v1/care-plans", headers=headers).json() == {"items": []}

    older = import_plan(signed_in.user["id"], title="Older plan", period_start="2025-01-01", period_end="2025-12-31", status="completed")
    active = import_plan(signed_in.user["id"])
    draft = import_plan(signed_in.user["id"], title="Draft plan", status="draft", goals=[])

    reply = client.get("/v1/care-plans", headers=headers)
    assert reply.status_code == 200, reply.text
    assert ids(reply) == [active["id"]]
    assert reply.json()["items"][0] == {
        "id": active["id"],
        "title": "Diabetes care plan",
        "description": "Keep A1c and blood pressure in range.",
        "status": "active",
        "period_start": "2026-04-01",
        "period_end": None,
        "author": "Dr. A. Patel",
        "goal_count": 2,
        "source": {"organization": "Example Health", "fhir_type": "CarePlan"},
    }
    assert ids(client.get("/v1/care-plans?status=completed", headers=headers)) == [older["id"]]
    assert ids(client.get("/v1/care-plans?status=all", headers=headers)) == [active["id"], draft["id"], older["id"]]
    assert client.get("/v1/care-plans?status=paused", headers=headers).status_code == 400


def test_detail_has_goals_with_targets_and_activities(client, signed_in):
    headers = signed_in.headers
    plan = import_plan(signed_in.user["id"])
    reply = client.get(f"/v1/care-plans/{plan['id']}", headers=headers)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["title"] == "Diabetes care plan" and body["goal_count"] == 2

    goals = {goal["description"]: goal for goal in body["goals"]}
    assert goals["Keep A1c below 7%"] == {
        "id": plan["goals"]["Keep A1c below 7%"],
        "description": "Keep A1c below 7%",
        "target": {"code": "4548-4", "value": 7.0, "unit": "%"},
        "due_date": "2027-03-31",
        "status": "active",
        "journey_id": None,
    }
    walk = goals["Walk after dinner most evenings"]
    assert walk["target"] is None and walk["due_date"] is None and walk["status"] == "proposed"

    activities = {activity["description"]: activity for activity in body["activities"]}
    lab = activities["A1c test every 3 months"]
    assert (lab["kind"], lab["status"], lab["scheduled_for"]) == ("lab", "scheduled", "2026-12-15")
    assert lab["id"]
    nutrition = activities["Diabetes nutrition class"]
    assert (nutrition["kind"], nutrition["status"], nutrition["scheduled_for"]) == ("education", "not_started", None)

    missing = client.get(f"/v1/care-plans/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


def test_users_only_see_their_own_plans(client, fake_provider, signed_in):
    plan = import_plan(signed_in.user["id"])
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com", given_name="Bob").json())
    assert client.get("/v1/care-plans", headers=other).json()["items"] == []
    assert client.get(f"/v1/care-plans/{plan['id']}", headers=other).status_code == 404
    assert client.get("/v1/care-plans").status_code == 401


def test_import_checks_the_plan_before_it_saves_anything(signed_in):
    user_id = uuid.UUID(signed_in.user["id"])
    with SessionLocal() as db:
        with pytest.raises(ValidationError):
            import_care_plan(db, user_id, {**DIABETES_PLAN, "status": "paused"})
        with pytest.raises(ValidationError):
            import_care_plan(db, user_id, {**DIABETES_PLAN, "goals": [{"description": ""}]})
        with pytest.raises(ValidationError):
            import_care_plan(db, user_id, {**DIABETES_PLAN, "activities": [{"kind": "lab", "description": "x", "status": "done"}]})
        with pytest.raises(ValidationError):
            import_care_plan(db, user_id, {**DIABETES_PLAN, "notes": "extra"})
        minimal = import_care_plan(db, user_id, {"title": "Just a title"})
        assert minimal.status == "active" and minimal.goals == [] and minimal.activities == []


def test_a_goal_becomes_a_journey_once(client, signed_in):
    headers = signed_in.headers
    plan = import_plan(signed_in.user["id"])
    goal_id = plan["goals"]["Keep A1c below 7%"]
    url = f"/v1/care-plans/{plan['id']}/goals/{goal_id}/journey"

    started = client.post(url, json={"title": "Keep my A1c steady", "why": "I want to keep up with my grandkids"}, headers=headers)
    assert started.status_code == 201, started.text
    journey = started.json()
    assert journey == {
        "id": journey["id"],
        "title": "Keep my A1c steady",
        "why": "I want to keep up with my grandkids",
        "plan_goal_id": goal_id,
        "status": "active",
        "habits": [],
    }
    assert client.get(f"/v1/journeys/{journey['id']}", headers=headers).json()["plan_goal_id"] == goal_id
    goals = {goal["id"]: goal for goal in client.get(f"/v1/care-plans/{plan['id']}", headers=headers).json()["goals"]}
    assert goals[goal_id]["journey_id"] == journey["id"]

    again = client.post(url, json={"title": "Another"}, headers=headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "journey_exists"
    assert again.json()["error"]["journey_id"] == journey["id"]
    direct = client.post("/v1/journeys", json={"title": "Another", "plan_goal_id": goal_id}, headers=headers)
    assert direct.status_code == 409 and direct.json()["error"]["code"] == "journey_exists"

    other_plan = import_plan(signed_in.user["id"], title="Other plan")
    wrong_plan = client.post(f"/v1/care-plans/{other_plan['id']}/goals/{goal_id}/journey", json={}, headers=headers)
    assert wrong_plan.status_code == 404
    assert client.post(f"/v1/care-plans/{plan['id']}/goals/{uuid.uuid4()}/journey", json={}, headers=headers).status_code == 404
    assert client.post(url, json={"title": "x", "habits": []}, headers=headers).status_code == 400

    # Deleting the journey frees the goal, and a bare request takes the goal's own words as the title.
    assert client.delete(f"/v1/journeys/{journey['id']}", headers=headers).status_code == 204
    goals = {goal["id"]: goal for goal in client.get(f"/v1/care-plans/{plan['id']}", headers=headers).json()["goals"]}
    assert goals[goal_id]["journey_id"] is None
    fresh = client.post(url, headers=headers)
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["title"] == "Keep A1c below 7%" and fresh.json()["why"] == "" and fresh.json()["plan_goal_id"] == goal_id

    walk_goal = plan["goals"]["Walk after dinner most evenings"]
    from_list = client.post("/v1/journeys", json={"title": "Evening walks", "plan_goal_id": walk_goal}, headers=headers)
    assert from_list.status_code == 201 and from_list.json()["plan_goal_id"] == walk_goal
    goals = {goal["id"]: goal for goal in client.get(f"/v1/care-plans/{plan['id']}", headers=headers).json()["goals"]}
    assert goals[walk_goal]["journey_id"] == from_list.json()["id"]
