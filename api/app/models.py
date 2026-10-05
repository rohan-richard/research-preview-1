import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, Text, Time, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship

from app.clock import now


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True), dict: JSONB}


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())

    identities: Mapped[list["Identity"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    profile: Mapped["Profile"] = relationship(cascade="all, delete-orphan")
    settings: Mapped["UserSettings"] = relationship(cascade="all, delete-orphan")


class Identity(Base):
    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="identities")


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(Text, unique=True)
    platform: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())

    user: Mapped[User] = relationship()


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    preferred_name: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str | None] = mapped_column(Text)
    profession: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    onboarding_step: Mapped[str] = mapped_column(Text, default="about_you", server_default="about_you")
    onboarding_completed_at: Mapped[datetime | None]
    chat_synced_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tone: Mapped[str] = mapped_column(Text, default="straight_talk", server_default="straight_talk")
    reply_length: Mapped[str] = mapped_column(Text, default="balanced", server_default="balanced")
    ai_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    notification_categories: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'"))
    quiet_start: Mapped[int] = mapped_column(SmallInteger, default=21, server_default="21")
    quiet_end: Mapped[int] = mapped_column(SmallInteger, default=8, server_default="8")
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    call_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    phone: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (Index("ix_consents_user_scope_changed", "user_id", "scope", "changed_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(Text)
    granted: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())


class DataRequest(Base):
    __tablename__ = "data_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    file_key: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    completed_at: Mapped[datetime | None]


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(Text, default="queued", server_default="queued")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    run_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    locked_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)


class ChatServerOutbox(Base):
    __tablename__ = "chat_server_outbox"

    # No foreign key: a delete row must outlive the user it is about.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appointments_user_starts", "user_id", "starts_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(Text, default="patient", server_default="patient")
    # Layer 3 adds the fhir_resources table, so there is no foreign key yet.
    fhir_resource_id: Mapped[uuid.UUID | None]
    clinician: Mapped[str | None] = mapped_column(Text)
    organization: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="confirmed", server_default="confirmed")
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    join_link: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())

    prep: Mapped["VisitPrep | None"] = relationship(cascade="all, delete-orphan")


class VisitPrep(Base):
    __tablename__ = "visit_preps"

    appointment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    step: Mapped[str] = mapped_column(Text, default="focus", server_default="focus")
    goal: Mapped[str] = mapped_column(Text, default="", server_default="")
    changes: Mapped[str] = mapped_column(Text, default="", server_default="")
    medication_concerns: Mapped[str] = mapped_column(Text, default="", server_default="")
    questions: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'"))
    practical_needs: Mapped[str] = mapped_column(Text, default="", server_default="")
    reviewed_at: Mapped[datetime | None]
    reviewed_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    # Only PUT moves this. If-Match compares it, so a review or a cleared review must not change it.
    updated_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())


class VisitPrepLog(Base):
    __tablename__ = "visit_prep_logs"

    appointment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visit_preps.appointment_id", ondelete="CASCADE"), primary_key=True)
    log_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("logs.id", ondelete="CASCADE"), primary_key=True)


class GuideItem(Base):
    __tablename__ = "guide_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(Text)
    # Declared before the "text" column below, which shadows sqlalchemy.text in this class body.
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    text: Mapped[str] = mapped_column(Text)
    added_from: Mapped[str | None] = mapped_column(Text)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class Log(Base):
    __tablename__ = "logs"
    __table_args__ = (Index("ix_logs_user_kind_taken", "user_id", "kind", "taken_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    value: Mapped[dict] = mapped_column(JSONB)
    taken_at: Mapped[datetime]
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="patient", server_default="patient")
    # Layer 3 adds the medications table, so there is no foreign key yet.
    medication_id: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    route: Mapped[str] = mapped_column(Text)
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())


class ContentItem(Base):
    __tablename__ = "content_items"
    __table_args__ = (UniqueConstraint("type", "slug", "locale"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, default="en-US", server_default="en-US")
    data: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    published_at: Mapped[datetime | None]
    retired_at: Mapped[datetime | None]


class ContentProgress(Base):
    __tablename__ = "content_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True)
    position_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completed_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class CarePlan(Base):
    __tablename__ = "care_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Layer 3 adds the fhir_resources table, so there is no foreign key yet.
    fhir_resource_id: Mapped[uuid.UUID | None]
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    author: Mapped[str | None] = mapped_column(Text)
    organization: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())

    goals: Mapped[list["CarePlanGoal"]] = relationship(cascade="all, delete-orphan", order_by="CarePlanGoal.created_at, CarePlanGoal.id")
    activities: Mapped[list["CarePlanActivity"]] = relationship(
        cascade="all, delete-orphan", order_by="CarePlanActivity.created_at, CarePlanActivity.id"
    )


class CarePlanGoal(Base):
    __tablename__ = "care_plan_goals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    care_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_plans.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    fhir_resource_id: Mapped[uuid.UUID | None]
    description: Mapped[str] = mapped_column(Text)
    target_code: Mapped[str | None] = mapped_column(Text)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    target_unit: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    # use_alter breaks the cycle with journeys.plan_goal_id, so the tables can be created and truncated in order.
    journey_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journeys.id", ondelete="SET NULL", use_alter=True, name="fk_care_plan_goals_journey_id")
    )
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class CarePlanActivity(Base):
    __tablename__ = "care_plan_activities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    care_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_plans.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="not_started", server_default="not_started")
    scheduled_for: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class Journey(Base):
    __tablename__ = "journeys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text, default="", server_default="")
    plan_goal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("care_plan_goals.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())

    habits: Mapped[list["Habit"]] = relationship(back_populates="journey", cascade="all, delete-orphan", order_by="Habit.created_at, Habit.id")


class Habit(Base):
    __tablename__ = "habits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    journey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journeys.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    cue: Mapped[str | None] = mapped_column(Text)
    barrier: Mapped[str | None] = mapped_column(Text)
    fallback: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    pace: Mapped[str] = mapped_column(Text, default="small_steps", server_default="small_steps")
    reminder_time: Mapped[time | None] = mapped_column(Time)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    origin: Mapped[str] = mapped_column(Text, default="patient", server_default="patient")
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())

    journey: Mapped[Journey] = relationship(back_populates="habits")


class HabitCheckIn(Base):
    __tablename__ = "habit_check_ins"
    __table_args__ = (UniqueConstraint("habit_id", "date"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    habit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column("date", Date)
    outcome: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    plan_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class PushDevice(Base):
    __tablename__ = "push_devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    apns_token: Mapped[str | None] = mapped_column(Text)
    apns_environment: Mapped[str | None] = mapped_column(Text)
    web_endpoint: Mapped[str | None] = mapped_column(Text, unique=True)
    web_p256dh: Mapped[str | None] = mapped_column(Text)
    web_auth: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    failure_count: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    last_sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        Index("ix_notifications_status_scheduled", "status", "scheduled_for"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(Text)
    # Points at a habit, appointment, or medication row in another table, so there is no foreign key.
    source_id: Mapped[uuid.UUID | None]
    category: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(Text)
    scheduled_for: Mapped[datetime]
    status: Mapped[str] = mapped_column(Text, default="scheduled", server_default="scheduled")
    skip_reason: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]
    opened_at: Mapped[datetime | None]
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("push_devices.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    deleted_at: Mapped[datetime | None]


class AuditLog(Base):
    __tablename__ = "audit_log"

    # No foreign key on user_id: the rows must outlive the user they are about.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None]
    user_id: Mapped[uuid.UUID]
    action: Mapped[str] = mapped_column(Text)
    resource: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[uuid.UUID | None]
    ip: Mapped[str | None] = mapped_column(INET)
    at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())


class EhrConnection(Base):
    __tablename__ = "ehr_connections"
    __table_args__ = (UniqueConstraint("source", "org_connection_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(Text, default="fasten", server_default="fasten")
    org_connection_id: Mapped[str] = mapped_column(Text)
    organization: Mapped[str] = mapped_column(Text)
    platform_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    scope: Mapped[str | None] = mapped_column(Text)
    consent_expires_at: Mapped[datetime | None]
    connected_at: Mapped[datetime | None]
    last_synced_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())


class EhrSyncJob(Base):
    __tablename__ = "ehr_sync_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ehr_connections.id", ondelete="CASCADE"), index=True)
    external_task_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="requested", server_default="requested")
    resource_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    completed_at: Mapped[datetime | None]


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    signature_verified: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, default="received", server_default="received")
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    processed_at: Mapped[datetime | None]


class FhirResource(Base):
    __tablename__ = "fhir_resources"
    __table_args__ = (
        UniqueConstraint("connection_id", "resource_type", "fhir_id"),
        Index("ix_fhir_resources_user_type", "user_id", "resource_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ehr_connections.id", ondelete="CASCADE"))
    resource_type: Mapped[str] = mapped_column(Text)
    fhir_id: Mapped[str] = mapped_column(Text)
    version_id: Mapped[str | None] = mapped_column(Text)
    last_updated: Mapped[datetime | None]
    # Deferred: the record routes read the connection through this row and never need the raw JSON.
    resource: Mapped[dict] = mapped_column(JSONB, deferred=True)
    sync_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ehr_sync_jobs.id", ondelete="SET NULL"))
    removed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now())

    connection: Mapped[EhrConnection] = relationship()


class EhrRecord:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4, sort_order=-10)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, sort_order=-9)
    fhir_resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fhir_resources.id", ondelete="CASCADE"), index=True, sort_order=-8)
    code_system: Mapped[str | None] = mapped_column(Text, sort_order=-7)
    code: Mapped[str | None] = mapped_column(Text, sort_order=-6)
    display: Mapped[str | None] = mapped_column(Text, sort_order=-5)
    created_at: Mapped[datetime] = mapped_column(default=now, server_default=func.now(), sort_order=10)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now, server_default=func.now(), sort_order=11)

    @declared_attr
    def resource(cls) -> Mapped[FhirResource]:
        return relationship()


class Condition(EhrRecord, Base):
    __tablename__ = "conditions"

    clinical_status: Mapped[str] = mapped_column(Text)
    onset_date: Mapped[date | None] = mapped_column(Date)
    abatement_date: Mapped[date | None] = mapped_column(Date)
    recorded_date: Mapped[date | None] = mapped_column(Date)


class Allergy(EhrRecord, Base):
    __tablename__ = "allergies"

    criticality: Mapped[str | None] = mapped_column(Text)
    reaction: Mapped[str | None] = mapped_column(Text)
    clinical_status: Mapped[str] = mapped_column(Text)
    recorded_date: Mapped[date | None] = mapped_column(Date)


class Medication(EhrRecord, Base):
    __tablename__ = "medications"

    status: Mapped[str] = mapped_column(Text)
    dose_text: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    prescriber: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    refills_allowed: Mapped[int | None] = mapped_column(Integer)
    days_supply: Mapped[int | None] = mapped_column(Integer)


class MedicationFill(EhrRecord, Base):
    __tablename__ = "medication_fills"

    medication_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"), index=True)
    dispensed_at: Mapped[datetime | None]
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    days_supply: Mapped[int | None] = mapped_column(Integer)
    pharmacy: Mapped[str | None] = mapped_column(Text)
    expected_refill_date: Mapped[date | None] = mapped_column(Date)


class LabReport(EhrRecord, Base):
    __tablename__ = "lab_reports"

    status: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime | None]
    performer: Mapped[str | None] = mapped_column(Text)


class LabResult(EhrRecord, Base):
    __tablename__ = "lab_results"
    __table_args__ = (Index("ix_lab_results_user_code_effective", "user_id", "code", "effective_at"),)

    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lab_reports.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(Text)
    value_number: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    range_low: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    range_high: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    interpretation: Mapped[str | None] = mapped_column(Text)
    effective_at: Mapped[datetime | None]


class Encounter(EhrRecord, Base):
    __tablename__ = "encounters"
    __table_args__ = (Index("ix_encounters_user_start", "user_id", "start_at"),)

    encounter_class: Mapped[str] = mapped_column("class", Text)
    type: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime]
    end_at: Mapped[datetime | None]
    practitioner: Mapped[str | None] = mapped_column(Text)
    organization: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)


class CareTeamMember(EhrRecord, Base):
    __tablename__ = "care_team_members"

    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    organization: Mapped[str | None] = mapped_column(Text)
    npi: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
