import logging
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import ehr, storage
from app.clock import now
from app.models import DataRequest, File, IdempotencyKey, Log

logger = logging.getLogger(__name__)
KEEP = timedelta(hours=24)


def run(db: Session) -> None:
    cutoff = now() - KEEP
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff))
    db.execute(delete(Log).where(Log.deleted_at < cutoff))
    for file in db.scalars(select(File).where(File.deleted_at < cutoff)).all():
        try:
            storage.delete(file.storage_key)
        except Exception as exc:
            logger.warning("could not remove %s, will try again next tick: %s", file.storage_key, exc)
            continue
        db.delete(file)
    db.execute(
        update(DataRequest)
        .where(DataRequest.kind == "export", DataRequest.status.in_(("pending", "ready")), DataRequest.requested_at < cutoff)
        .values(status="expired")
    )
    ehr.resync_due(db)
    db.commit()


def tick(db: Session) -> None:
    try:
        run(db)
    except Exception:
        db.rollback()
        logger.exception("maintenance tick failed")
