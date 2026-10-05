import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, select
from sqlalchemy.orm import Session, selectinload

from app import journeys
from app.audit import Audit
from app.auth import DB, Auth
from app.errors import ApiError
from app.idempotency import Idempotent
from app.models import CarePlan, CarePlanActivity, CarePlanGoal

router = APIRouter(prefix="/v1/care-plans")

PlanStatus = Literal["draft", "active", "completed", "revoked"]
GoalStatus = Literal["proposed", "active", "achieved", "cancelled"]
ActivityKind = Literal["appointment", "lab", "medication", "education", "other"]
ActivityStatus = Literal["not_started", "scheduled", "in_progress", "completed", "cancelled"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoalImport(Strict):
    fhir_resource_id: uuid.UUID | None = None
    description: str = Field(min_length=1, max_length=1000)
    target_code: str | None = Field(default=None, max_length=50)
    target_value: Decimal | None = None
    target_unit: str | None = Field(default=None, max_length=50)
    due_date: date | None = None
    status: GoalStatus = "active"


class ActivityImport(Strict):
    kind: ActivityKind
    description: str = Field(min_length=1, max_length=1000)
    status: ActivityStatus = "not_started"
    scheduled_for: date | None = None


class JourneyFromGoal(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    why: str = Field(default="", max_length=2000)


class CarePlanImport(Strict):
    fhir_resource_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    status: PlanStatus = "active"
    period_start: date | None = None
    period_end: date | None = None
    author: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    goals: list[GoalImport] = Field(default_factory=list, max_length=100)
    activities: list[ActivityImport] = Field(default_factory=list, max_length=200)


def import_care_plan(db: Session, user_id: uuid.UUID, plan: dict) -> CarePlan:
    body = CarePlanImport.model_validate(plan)
    row = CarePlan(user_id=user_id, **body.model_dump(exclude={"goals", "activities"}))
    row.goals = [CarePlanGoal(user_id=user_id, **goal.model_dump()) for goal in body.goals]
    row.activities = [CarePlanActivity(user_id=user_id, **activity.model_dump()) for activity in body.activities]
    db.add(row)
    db.flush()
    return row


def day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def plan_out(plan: CarePlan) -> dict:
    return {
        "id": str(plan.id),
        "title": plan.title,
        "description": plan.description,
        "status": plan.status,
        "period_start": day(plan.period_start),
        "period_end": day(plan.period_end),
        "author": plan.author,
        "goal_count": len(plan.goals),
        "source": {"organization": plan.organization, "fhir_type": "CarePlan"},
    }


def goal_out(goal: CarePlanGoal) -> dict:
    target = None
    if goal.target_code:
        value = float(goal.target_value) if goal.target_value is not None else None
        target = {"code": goal.target_code, "value": value, "unit": goal.target_unit}
    return {
        "id": str(goal.id),
        "description": goal.description,
        "target": target,
        "due_date": day(goal.due_date),
        "status": goal.status,
        "journey_id": str(goal.journey_id) if goal.journey_id else None,
    }


def activity_out(activity: CarePlanActivity) -> dict:
    return {
        "id": str(activity.id),
        "kind": activity.kind,
        "description": activity.description,
        "status": activity.status,
        "scheduled_for": day(activity.scheduled_for),
    }


def load_plan(db: Session, user_id: uuid.UUID, plan_id: uuid.UUID) -> CarePlan:
    plan = db.get(CarePlan, plan_id)
    if plan is None or plan.user_id != user_id:
        raise ApiError(404, "not_found", "No care plan with that id.")
    return plan


@router.get("")
def list_plans(auth: Auth, db: DB, audit: Audit, status: Literal["active", "completed", "all"] = "active") -> dict:
    user, _ = auth
    query = (
        select(CarePlan)
        .where(CarePlan.user_id == user.id)
        .options(selectinload(CarePlan.goals))
        .order_by(case((CarePlan.status == "active", 0), else_=1), CarePlan.period_start.desc().nulls_last(), CarePlan.created_at.desc())
    )
    if status != "all":
        query = query.where(CarePlan.status == status)
    items = [plan_out(plan) for plan in db.scalars(query)]
    audit.record("read", "care_plans")
    db.commit()
    return {"items": items}


@router.get("/{plan_id}")
def get_plan(plan_id: uuid.UUID, auth: Auth, db: DB) -> dict:
    plan = load_plan(db, auth[0].id, plan_id)
    return plan_out(plan) | {"goals": [goal_out(goal) for goal in plan.goals], "activities": [activity_out(a) for a in plan.activities]}


@router.post("/{plan_id}/goals/{goal_id}/journey", status_code=201)
def start_journey_from_goal(
    plan_id: uuid.UUID, goal_id: uuid.UUID, auth: Auth, db: DB, audit: Audit, idempotency: Idempotent, body: JourneyFromGoal | None = None
) -> dict:
    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    plan = load_plan(db, user.id, plan_id)
    goal = journeys.load_goal(db, user.id, goal_id)
    if goal.care_plan_id != plan.id:
        raise ApiError(404, "not_found", "No care-plan goal with that id.")
    title = (body and body.title) or goal.description
    journey = journeys.start_journey(db, user.id, title, body.why if body else "", goal)
    out = journeys.journey_out(db, journey, journeys.local_today(user.profile))
    audit.record("create", "journeys", journey.id)
    idempotency.store(201, out)
    db.commit()
    return out
