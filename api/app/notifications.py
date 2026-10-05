import logging
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import push_send
from app.clock import now
from app.models import Appointment, Habit, Journey, Notification, NotificationDelivery, Profile, PushDevice, UserSettings

logger = logging.getLogger(__name__)

TITLE = "Rumi"
DAILY_LIMIT = 2
WEEKLY_LIMIT = 8
MAX_FAILURES = 5
# TODO Layer 3: add the refill source (5 days before medications.expected_refill_date, "A refill is coming up",
# /medications) and the records source (when a sync adds new results, "New results are in", /records).


def zone(profile: Profile) -> ZoneInfo:
    return ZoneInfo(profile.timezone or "UTC")


def payload_for(row: Notification) -> dict:
    return {"id": str(row.id), "title": row.title, "body": row.body, "link": row.link, "category": row.category}


def habit_reminders(db: Session, at: datetime) -> list[Notification]:
    query = (
        select(Habit, Profile)
        .join(Journey, Habit.journey_id == Journey.id)
        .join(Profile, Profile.user_id == Habit.user_id)
        .where(Habit.deleted_at.is_(None), Habit.paused.is_(False), Habit.reminder_time.is_not(None), Journey.status == "active")
    )
    out = []
    for habit, profile in db.execute(query):
        tz = zone(profile)
        due = datetime.combine(at.astimezone(tz).date(), habit.reminder_time, tzinfo=tz)
        if due > at:
            out.append(
                Notification(
                    user_id=habit.user_id,
                    source="habit",
                    source_id=habit.id,
                    category="habit_moments",
                    title=TITLE,
                    body=f"Time for: {habit.title}",
                    link="/today",
                    scheduled_for=due,
                    idempotency_key=f"habit:{habit.id}:{due.date().isoformat()}",
                )
            )
    return out


def visit_reminders(db: Session, at: datetime) -> list[Notification]:
    query = (
        select(Appointment, Profile)
        .join(Profile, Profile.user_id == Appointment.user_id)
        .options(selectinload(Appointment.prep))
        .where(Appointment.status != "cancelled", Appointment.starts_at > at)
    )
    out = []
    for appointment, profile in db.execute(query):
        when = appointment.starts_at.astimezone(zone(profile)).strftime("%H:%M")
        common = dict(user_id=appointment.user_id, source_id=appointment.id, category="logistics", title=TITLE)
        link = f"/visits/{appointment.id}"
        for suffix, before, body in (("1d", timedelta(days=1), f"Visit tomorrow at {when}"), ("2h", timedelta(hours=2), f"Visit today at {when}")):
            due = appointment.starts_at - before
            if due > at:
                out.append(Notification(**common, source="visit", body=body, link=link, scheduled_for=due, idempotency_key=f"visit:{appointment.id}:{suffix}"))
        due = appointment.starts_at - timedelta(days=2)
        prep = appointment.prep
        if due > at and (prep is None or prep.reviewed_at is None):
            out.append(
                Notification(
                    **common,
                    source="visit_prep",
                    body="Get ready for your visit",
                    link=f"{link}/prep",
                    scheduled_for=due,
                    idempotency_key=f"visit_prep:{appointment.id}:2d",
                )
            )
    return out


def schedule_due(db: Session, at: datetime) -> int:
    wanted = {row.idempotency_key: row for row in habit_reminders(db, at) + visit_reminders(db, at)}
    if not wanted:
        return 0
    for existing in db.scalars(select(Notification).where(Notification.idempotency_key.in_(wanted))):
        fresh = wanted.pop(existing.idempotency_key)
        # A rescheduled visit or a changed reminder time moves a row that has not gone out yet.
        if existing.status == "scheduled" and (existing.scheduled_for, existing.body) != (fresh.scheduled_for, fresh.body):
            existing.scheduled_for = fresh.scheduled_for
            existing.body = fresh.body
    db.add_all(wanted.values())
    return len(wanted)


def add_nudge(db: Session, user_id: uuid.UUID, content: str, idempotency_key: str) -> Notification:
    row = db.scalar(select(Notification).where(Notification.user_id == user_id, Notification.idempotency_key == idempotency_key))
    if row is None:
        row = Notification(
            user_id=user_id,
            source="chat_nudge",
            category="check_ins",
            title=TITLE,
            body=content,
            link="/chat",
            scheduled_for=now(),
            idempotency_key=idempotency_key,
        )
        db.add(row)
        db.flush()
    return row


def in_quiet_hours(local: datetime, prefs: UserSettings) -> bool:
    start, end = prefs.quiet_start, prefs.quiet_end
    if start == end:
        return False
    if start < end:
        return start <= local.hour < end
    return local.hour >= start or local.hour < end


def next_quiet_end(local: datetime, end_hour: int) -> datetime:
    candidate = local.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def sent_since(db: Session, user_id: uuid.UUID, since: datetime) -> int:
    query = select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id, Notification.status == "sent", Notification.source != "visit", Notification.sent_at >= since
    )
    return db.scalar(query)


def stale_reason(db: Session, row: Notification, prefs: UserSettings, at: datetime) -> str | None:
    if row.source == "chat_nudge":
        return "paused" if prefs.ai_paused else None
    if row.source == "habit":
        habit = db.get(Habit, row.source_id)
        if habit is None or habit.deleted_at is not None or habit.journey.status != "active":
            return "stale"
        return "paused" if habit.paused else None
    if row.source in ("visit", "visit_prep"):
        appointment = db.get(Appointment, row.source_id)
        if appointment is None or appointment.status == "cancelled" or appointment.starts_at <= at:
            return "stale"
        if row.source == "visit_prep" and appointment.prep is not None and appointment.prep.reviewed_at is not None:
            return "stale"
    return None


def skip(row: Notification, reason: str) -> None:
    row.status = "skipped"
    row.skip_reason = reason


def push_to_device(device: PushDevice, payload: dict, at: datetime) -> str | None:
    send = push_send.send_web if device.platform == "web" else push_send.send_apns
    try:
        send(device, payload)
    except push_send.DeadDevice as exc:
        device.enabled = False
        device.failure_count += 1
        return str(exc)
    except Exception as exc:
        device.failure_count += 1
        if device.failure_count >= MAX_FAILURES:
            device.enabled = False
        return str(exc)[:2000]
    device.failure_count = 0
    device.last_sent_at = at
    return None


def send_one(db: Session, row: Notification, at: datetime) -> None:
    prefs = db.get(UserSettings, row.user_id)
    local = at.astimezone(zone(db.get(Profile, row.user_id)))
    if not prefs.push_enabled or not prefs.notification_categories.get(row.category, True):
        return skip(row, "category_off")
    if in_quiet_hours(local, prefs):
        if row.source == "chat_nudge":
            return skip(row, "quiet_hours")
        row.scheduled_for = next_quiet_end(local, prefs.quiet_end)
        return
    if row.source != "visit":
        day_start = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
        if sent_since(db, row.user_id, day_start) >= DAILY_LIMIT:
            return skip(row, "daily_limit")
        if sent_since(db, row.user_id, day_start - timedelta(days=local.weekday())) >= WEEKLY_LIMIT:
            return skip(row, "weekly_limit")
    reason = stale_reason(db, row, prefs, at)
    if reason:
        return skip(row, reason)
    devices = db.scalars(select(PushDevice).where(PushDevice.user_id == row.user_id, PushDevice.enabled.is_(True))).all()
    if not devices:
        return skip(row, "no_device")
    payload = payload_for(row)
    delivered = False
    for device in devices:
        error = push_to_device(device, payload, at)
        delivered = delivered or error is None
        db.add(
            NotificationDelivery(
                user_id=row.user_id,
                notification_id=row.id,
                device_id=device.id,
                status="failed" if error else "sent",
                error=error,
                sent_at=None if error else at,
            )
        )
    row.status = "sent" if delivered else "failed"
    row.sent_at = at if delivered else None


def send_due(db: Session, at: datetime) -> int:
    count = 0
    while True:
        row = db.scalar(
            select(Notification)
            .where(Notification.status == "scheduled", Notification.scheduled_for <= at)
            .order_by(Notification.scheduled_for, Notification.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return count
        try:
            send_one(db, row, at)
            # One commit per row: the push already went out, so a later failure must not roll this row back.
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("notification %s failed", row.id)
            db.get(Notification, row.id).status = "failed"
            db.commit()
        count += 1


def tick(db: Session) -> None:
    try:
        schedule_due(db, now())
        db.commit()
        send_due(db, now())
    except Exception:
        db.rollback()
        logger.exception("notification tick failed")
