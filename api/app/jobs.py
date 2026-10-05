import json
import logging
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, chat_server, ehr, storage
from app.clock import iso, now
from app.models import AuthSession, ChatServerOutbox, Consent, DataRequest, EhrSyncJob, Identity, Job, Profile, User, UserSettings

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def enqueue(db: Session, kind: str, payload: dict) -> Job:
    job = Job(kind=kind, payload=payload)
    db.add(job)
    return job


def backoff(attempts: int) -> timedelta:
    return timedelta(minutes=2**attempts)


def columns(row) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def export_user_data(db: Session, user_id: uuid.UUID) -> dict:
    user = db.get(User, user_id)
    profile = db.get(Profile, user_id)
    prefs = db.get(UserSettings, user_id)
    return {
        "exported_at": iso(now()),
        "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name, "created_at": iso(user.created_at)},
        "identities": [
            {"provider": i.provider, "email": i.email, "created_at": iso(i.created_at)}
            for i in db.scalars(select(Identity).where(Identity.user_id == user_id))
        ],
        "sessions": [
            {"platform": s.platform, "created_at": iso(s.created_at), "revoked_at": iso(s.revoked_at)}
            for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user_id))
        ],
        "profile": columns(profile),
        "settings": columns(prefs),
        "consents": [columns(c) for c in db.scalars(select(Consent).where(Consent.user_id == user_id).order_by(Consent.changed_at))],
        "data_requests": [columns(r) for r in db.scalars(select(DataRequest).where(DataRequest.user_id == user_id))],
    }


def run_export(db: Session, payload: dict) -> None:
    request = db.get(DataRequest, uuid.UUID(payload["request_id"]))
    if request is None:
        return
    data = export_user_data(db, request.user_id)
    key = f"exports/{request.user_id}/{request.id}.json"
    storage.put_bytes(key, json.dumps(data, indent=2, default=str).encode(), "application/json")
    request.file_key = key
    request.status = "ready"
    request.completed_at = now()
    audit.record(db, actor=None, user_id=request.user_id, action="export", resource="data_requests", resource_id=request.id)


def run_delete_account(db: Session, payload: dict) -> None:
    user = db.get(User, uuid.UUID(payload["user_id"]))
    if user is None:
        return
    chat_server.queue_delete(db, user.id)
    audit.record(db, actor=None, user_id=user.id, action="delete", resource="users", resource_id=user.id)
    db.delete(user)


HANDLERS = {
    "export": run_export,
    "delete_account": run_delete_account,
    "ehr_export": ehr.run_export,
    "ehr_webhook": ehr.run_webhook,
}


def run_one(db: Session) -> bool:
    job = db.scalar(
        select(Job).where(Job.status == "queued", Job.run_at <= now()).order_by(Job.run_at).limit(1).with_for_update(skip_locked=True)
    )
    if job is None:
        return False
    job.status = "running"
    job.locked_at = now()
    db.commit()
    try:
        HANDLERS[job.kind](db, job.payload)
        job.status = "done"
        job.locked_at = None
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("job %s (%s) failed", job.id, job.kind)
        job = db.get(Job, job.id)
        job.attempts += 1
        job.last_error = str(exc)[:2000]
        job.locked_at = None
        if job.attempts >= MAX_ATTEMPTS:
            job.status = "failed"
            if job.kind == "export":
                request = db.get(DataRequest, uuid.UUID(job.payload["request_id"]))
                if request is not None:
                    request.status = "failed"
            if job.kind == "ehr_export":
                sync = db.get(EhrSyncJob, uuid.UUID(job.payload["sync_job_id"]))
                if sync is not None and sync.status == "requested":
                    ehr.fail_job(sync, job.last_error)
        else:
            job.status = "queued"
            job.run_at = now() + backoff(job.attempts)
        db.commit()
    return True


def run_outbox_one(db: Session) -> bool:
    row = db.scalar(
        select(ChatServerOutbox)
        .where(ChatServerOutbox.status == "pending", ChatServerOutbox.next_attempt_at <= now())
        .order_by(ChatServerOutbox.next_attempt_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        return False
    # "running" is not in the spec's status list. It stops a new change from merging into a row
    # that is already on its way to the chat server.
    row.status = "running"
    db.commit()
    try:
        if row.kind == "sync":
            chat_server.sync_user(db, row.user_id)
        else:
            chat_server.delete_person(str(row.user_id))
        row.status = "done"
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("outbox %s (%s) failed: %s", row.id, row.kind, exc)
        row = db.get(ChatServerOutbox, row.id)
        row.attempts += 1
        row.last_error = str(exc)[:2000]
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
        else:
            row.status = "pending"
            row.next_attempt_at = now() + backoff(row.attempts)
        db.commit()
    return True
