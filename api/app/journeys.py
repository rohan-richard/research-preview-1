import uuid
from collections import defaultdict
from datetime import date, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import Audit
from app.auth import DB, Auth
from app.clock import iso, now
from app.errors import ApiError
from app.idempotency import Idempotent
from app.models import CarePlanGoal, Habit, HabitCheckIn, Journey, Profile

router = APIRouter(prefix="/v1/journeys")
habits_router = APIRouter(prefix="/v1/habits")

PLAN_FIELDS = ("title", "context", "reason", "cue", "barrier", "fallback", "confidence", "pace")
HABIT_FIELDS = PLAN_FIELDS + ("reminder_time", "origin")
REQUIRED_FIELDS = ("title", "pace", "origin")

JourneyStatus = Literal["active", "paused", "done"]
Pace = Literal["small_steps", "steady"]
Origin = Literal["patient", "rumi_suggestion", "care_plan"]
Outcome = Literal["kept", "fallback", "blocked", "skipped"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JourneyPost(Strict):
    title: str = Field(min_length=1, max_length=200)
    why: str = Field(default="", max_length=2000)
    plan_goal_id: uuid.UUID | None = None


class JourneyPatch(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    why: str | None = Field(default=None, max_length=2000)
    status: JourneyStatus | None = None


class HabitFields(Strict):
    context: str | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=2000)
    cue: str | None = Field(default=None, max_length=500)
    barrier: str | None = Field(default=None, max_length=500)
    fallback: str | None = Field(default=None, max_length=500)
    confidence: int | None = Field(default=None, ge=1, le=5)
    reminder_time: time | None = None


class HabitPost(HabitFields):
    title: str = Field(min_length=1, max_length=200)
    pace: Pace = "small_steps"
    origin: Origin = "patient"


class HabitPatch(HabitFields):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    pace: Pace | None = None
    origin: Origin | None = None
    paused: bool | None = None


class CheckInPut(Strict):
    outcome: Outcome
    note: str = Field(default="", max_length=1000)


def local_today(profile: Profile) -> date:
    return now().astimezone(ZoneInfo(profile.timezone or "UTC")).date()


def week_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def hhmm(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def live_habits(journey: Journey) -> list[Habit]:
    return [habit for habit in journey.habits if habit.deleted_at is None]


def habit_out(habit: Habit) -> dict:
    out = {"id": str(habit.id), "journey_id": str(habit.journey_id)}
    out.update({field: getattr(habit, field) for field in PLAN_FIELDS})
    out["reminder_time"] = hhmm(habit.reminder_time)
    out["paused"] = habit.paused
    out["origin"] = habit.origin
    out["updated_at"] = iso(habit.updated_at)
    return out


def habit_summary(habit: Habit) -> dict:
    return {"id": str(habit.id), "title": habit.title, "context": habit.context, "paused": habit.paused}


def check_in_out(row: HabitCheckIn) -> dict:
    return {"date": row.day.isoformat(), "outcome": row.outcome, "note": row.note}


def week_check_ins(db: Session, habits: list[Habit], today: date) -> dict[uuid.UUID, list[dict]]:
    weeks: dict[uuid.UUID, list[dict]] = defaultdict(list)
    if habits:
        query = (
            select(HabitCheckIn)
            .where(HabitCheckIn.habit_id.in_([habit.id for habit in habits]), HabitCheckIn.day >= week_start(today))
            .order_by(HabitCheckIn.day)
        )
        for row in db.scalars(query):
            weeks[row.habit_id].append({"date": row.day.isoformat(), "outcome": row.outcome})
    return weeks


def journeys_out(db: Session, journeys: list[Journey], today: date, full: bool) -> list[dict]:
    weeks = week_check_ins(db, [habit for journey in journeys for habit in live_habits(journey)], today)
    out = []
    for journey in journeys:
        habits = [
            (habit_out(habit) if full else habit_summary(habit)) | {"this_week": weeks.get(habit.id, [])} for habit in live_habits(journey)
        ]
        out.append(
            {
                "id": str(journey.id),
                "title": journey.title,
                "why": journey.why,
                "plan_goal_id": str(journey.plan_goal_id) if journey.plan_goal_id else None,
                "status": journey.status,
                "habits": habits,
            }
        )
    return out


def journey_out(db: Session, journey: Journey, today: date, full: bool = True) -> dict:
    return journeys_out(db, [journey], today, full)[0]


def load_journey(db: Session, user_id: uuid.UUID, journey_id: uuid.UUID) -> Journey:
    journey = db.get(Journey, journey_id)
    if journey is None or journey.user_id != user_id:
        raise ApiError(404, "not_found", "No journey with that id.")
    return journey


def load_habit(db: Session, user_id: uuid.UUID, habit_id: uuid.UUID) -> Habit:
    habit = db.get(Habit, habit_id)
    if habit is None or habit.user_id != user_id or habit.deleted_at is not None:
        raise ApiError(404, "not_found", "No habit with that id.")
    return habit


def load_goal(db: Session, user_id: uuid.UUID, goal_id: uuid.UUID) -> CarePlanGoal:
    goal = db.get(CarePlanGoal, goal_id)
    if goal is None or goal.user_id != user_id:
        raise ApiError(404, "not_found", "No care-plan goal with that id.")
    return goal


def start_journey(db: Session, user_id: uuid.UUID, title: str, why: str, goal: CarePlanGoal | None = None) -> Journey:
    if goal is not None and goal.journey_id is not None:
        raise ApiError(409, "journey_exists", "This goal already has a journey.", journey_id=str(goal.journey_id))
    journey = Journey(user_id=user_id, title=title, why=why, plan_goal_id=goal.id if goal else None)
    db.add(journey)
    db.flush()
    if goal is not None:
        goal.journey_id = journey.id
    return journey


def plan_snapshot(habit: Habit) -> dict:
    return {field: getattr(habit, field) for field in PLAN_FIELDS}


@router.get("")
def list_journeys(auth: Auth, db: DB, audit: Audit, status: Literal["active", "paused", "done", "all"] = "active") -> dict:
    user, _ = auth
    query = select(Journey).where(Journey.user_id == user.id).options(selectinload(Journey.habits)).order_by(Journey.created_at, Journey.id)
    if status != "all":
        query = query.where(Journey.status == status)
    items = journeys_out(db, db.scalars(query).all(), local_today(user.profile), full=False)
    audit.record("read", "journeys")
    db.commit()
    return {"items": items}


@router.post("", status_code=201)
def add_journey(body: JourneyPost, auth: Auth, db: DB, audit: Audit, idempotency: Idempotent) -> dict:
    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    goal = load_goal(db, user.id, body.plan_goal_id) if body.plan_goal_id else None
    journey = start_journey(db, user.id, body.title, body.why, goal)
    out = journey_out(db, journey, local_today(user.profile))
    audit.record("create", "journeys", journey.id)
    idempotency.store(201, out)
    db.commit()
    return out


@router.get("/{journey_id}")
def get_journey(journey_id: uuid.UUID, auth: Auth, db: DB) -> dict:
    user, _ = auth
    return journey_out(db, load_journey(db, user.id, journey_id), local_today(user.profile))


@router.patch("/{journey_id}")
def patch_journey(journey_id: uuid.UUID, body: JourneyPatch, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    journey = load_journey(db, user.id, journey_id)
    if body.title is not None:
        journey.title = body.title
    if body.why is not None:
        journey.why = body.why
    if body.status is not None and body.status != journey.status:
        if body.status == "paused":
            for habit in live_habits(journey):
                habit.paused = True
        elif journey.status == "paused":
            for habit in live_habits(journey):
                habit.paused = False
        journey.status = body.status
    audit.record("update", "journeys", journey.id)
    db.commit()
    return journey_out(db, journey, local_today(user.profile))


@router.delete("/{journey_id}", status_code=204)
def delete_journey(journey_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> None:
    user, _ = auth
    journey = load_journey(db, user.id, journey_id)
    db.delete(journey)
    audit.record("delete", "journeys", journey.id)
    db.commit()


@router.post("/{journey_id}/habits", status_code=201)
def add_habit(journey_id: uuid.UUID, body: HabitPost, auth: Auth, db: DB, audit: Audit, idempotency: Idempotent) -> dict:
    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    journey = load_journey(db, user.id, journey_id)
    habit = Habit(user_id=user.id, **body.model_dump())
    journey.habits.append(habit)
    db.flush()
    out = habit_out(habit)
    audit.record("create", "habits", habit.id)
    idempotency.store(201, out)
    db.commit()
    return out


@habits_router.get("/today")
def today(auth: Auth, db: DB) -> dict:
    user, _ = auth
    day = local_today(user.profile)
    query = (
        select(Habit)
        .join(Journey)
        .where(Habit.user_id == user.id, Habit.deleted_at.is_(None), Habit.paused.is_(False), Journey.status == "active")
        .order_by(Habit.reminder_time.nulls_last(), Habit.created_at, Habit.id)
    )
    habits = db.scalars(query).all()
    done = {}
    if habits:
        rows = db.scalars(select(HabitCheckIn).where(HabitCheckIn.habit_id.in_([habit.id for habit in habits]), HabitCheckIn.day == day))
        done = {row.habit_id: {"outcome": row.outcome, "note": row.note} for row in rows}
    return {
        "date": day.isoformat(),
        "items": [
            {
                "habit_id": str(habit.id),
                "title": habit.title,
                "context": habit.context,
                "fallback": habit.fallback,
                "reminder_time": hhmm(habit.reminder_time),
                "check_in": done.get(habit.id),
            }
            for habit in habits
        ],
    }


@habits_router.patch("/{habit_id}")
def patch_habit(habit_id: uuid.UUID, body: HabitPatch, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    habit = load_habit(db, user.id, habit_id)
    for field in body.model_fields_set:
        value = getattr(body, field)
        if value is None and field in REQUIRED_FIELDS:
            raise ApiError(400, "invalid_request", f"{field} cannot be empty.")
        setattr(habit, field, value)
    audit.record("update", "habits", habit.id)
    db.commit()
    return habit_out(habit)


@habits_router.delete("/{habit_id}", status_code=204)
def delete_habit(habit_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> None:
    user, _ = auth
    habit = load_habit(db, user.id, habit_id)
    habit.deleted_at = now()
    audit.record("delete", "habits", habit.id)
    db.commit()


@habits_router.get("/{habit_id}/check-ins")
def list_check_ins(
    habit_id: uuid.UUID, auth: Auth, db: DB, start: Annotated[date | None, Query(alias="from")] = None, to: date | None = None
) -> dict:
    user, _ = auth
    habit = load_habit(db, user.id, habit_id)
    query = select(HabitCheckIn).where(HabitCheckIn.habit_id == habit.id).order_by(HabitCheckIn.day)
    if start:
        query = query.where(HabitCheckIn.day >= start)
    if to:
        query = query.where(HabitCheckIn.day <= to)
    return {"items": [check_in_out(row) for row in db.scalars(query)]}


@habits_router.put("/{habit_id}/check-ins/{day}")
def put_check_in(habit_id: uuid.UUID, day: date, body: CheckInPut, auth: Auth, db: DB, audit: Audit) -> dict:
    user, _ = auth
    habit = load_habit(db, user.id, habit_id)
    if day > local_today(user.profile):
        raise ApiError(400, "invalid_date", "The date is after today.")
    if habit.paused:
        raise ApiError(409, "habit_paused", "Resume the habit before you check in.")
    row = db.scalar(select(HabitCheckIn).where(HabitCheckIn.habit_id == habit.id, HabitCheckIn.day == day))
    action = "update" if row else "create"
    if row is None:
        row = HabitCheckIn(user_id=user.id, habit_id=habit.id, day=day)
        db.add(row)
    row.outcome = body.outcome
    row.note = body.note
    row.plan_snapshot = plan_snapshot(habit)
    row.updated_at = now()
    db.flush()
    audit.record(action, "habit_check_ins", row.id)
    db.commit()
    return check_in_out(row)


@habits_router.delete("/{habit_id}/check-ins/{day}", status_code=204)
def delete_check_in(habit_id: uuid.UUID, day: date, auth: Auth, db: DB, audit: Audit) -> None:
    user, _ = auth
    habit = load_habit(db, user.id, habit_id)
    row = db.scalar(select(HabitCheckIn).where(HabitCheckIn.habit_id == habit.id, HabitCheckIn.day == day))
    if row is None:
        raise ApiError(404, "not_found", "No check-in on that date.")
    db.delete(row)
    audit.record("delete", "habit_check_ins", row.id)
    db.commit()
