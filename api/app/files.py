import logging
import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import storage
from app.audit import Audit
from app.auth import DB, Auth
from app.clock import iso, now
from app.errors import ApiError
from app.idempotency import Idempotent
from app.models import File

router = APIRouter(prefix="/v1/files")
logger = logging.getLogger(__name__)

MAX_BYTES = 20 * 1024 * 1024
UPLOAD_TTL = 15 * 60
DOWNLOAD_TTL = 10 * 60


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilePost(Strict):
    purpose: Literal["document", "log_photo", "export", "report"]
    content_type: str = Field(pattern=r"^[\w.+-]+/[\w.+-]+$", max_length=200)
    size_bytes: int = Field(gt=0, le=MAX_BYTES)


def load_file(db: Session, user_id: uuid.UUID, file_id: uuid.UUID) -> File:
    file = db.get(File, file_id)
    if file is None or file.user_id != user_id or file.deleted_at is not None:
        raise ApiError(404, "not_found", "No file with that id.")
    return file


@router.post("", status_code=201)
def start_upload(body: FilePost, auth: Auth, db: DB, audit: Audit, idempotency: Idempotent) -> dict:
    user, _ = auth
    if (stored := idempotency.replay()) is not None:
        return stored
    file = File(id=uuid.uuid4(), user_id=user.id, purpose=body.purpose, content_type=body.content_type, size_bytes=body.size_bytes)
    file.storage_key = f"files/{user.id}/{file.id}"
    db.add(file)
    issued = now()
    out = {
        "id": str(file.id),
        "upload_url": storage.upload_url(file.storage_key, file.content_type, UPLOAD_TTL),
        "expires_at": iso(issued + timedelta(seconds=UPLOAD_TTL)),
    }
    audit.record("create", "files", file.id)
    idempotency.store(201, out)
    db.commit()
    return out


# No access token here: the signed link is the permission, so the app can open it straight in a browser.
@router.get("/local/{key:path}")
def local_file(key: str, expires: int, signature: str) -> FileResponse:
    if not storage.local_link_valid(key, expires, signature):
        raise ApiError(403, "link_invalid", "The link is not valid or has expired.")
    try:
        path = storage.local_path(key)
    except ValueError:
        path = None
    if path is None or not path.is_file():
        raise ApiError(404, "not_found", "No file at that link.")
    return FileResponse(path, filename=path.name)


@router.get("/{file_id}")
def download_link(file_id: uuid.UUID, auth: Auth, db: DB) -> dict:
    file = load_file(db, auth[0].id, file_id)
    if file.status == "pending":
        if not storage.exists(file.storage_key):
            raise ApiError(409, "file_not_ready", "The upload has not finished yet.")
        file.status = "ready"
        db.commit()
    issued = now()
    return {
        "download_url": storage.download_url(file.storage_key, DOWNLOAD_TTL),
        "expires_at": iso(issued + timedelta(seconds=DOWNLOAD_TTL)),
    }


@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: uuid.UUID, auth: Auth, db: DB, audit: Audit) -> None:
    user, _ = auth
    file = load_file(db, user.id, file_id)
    file.deleted_at = now()
    try:
        storage.delete(file.storage_key)
    except Exception as exc:
        # The hourly cleanup tries again, so a storage error must not stop the delete.
        logger.warning("could not remove %s now: %s", file.storage_key, exc)
    audit.record("delete", "files", file.id)
    db.commit()
