import hashlib
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.auth import DB, Auth
from app.clock import iso, now
from app.errors import ApiError
from app.models import ContentItem, ContentProgress

router = APIRouter(prefix="/v1/content")

CURRENTS_FIELDS = ("title", "kind", "duration_seconds", "media_url", "image_url", "topics")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProgressPut(Strict):
    position_seconds: int = Field(ge=0)
    completed: bool = False


def published(item_type: str, domain: str | None = None) -> Select:
    query = select(ContentItem).where(
        ContentItem.type == item_type, ContentItem.published_at.is_not(None), ContentItem.retired_at.is_(None)
    )
    if domain is not None:
        query = query.where((ContentItem.domain == domain) | ContentItem.domain.is_(None))
    return query


def etag(parts: list[str]) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def send(body: dict, tag: str, if_none_match: str | None) -> Response:
    if if_none_match is not None and tag in [part.strip().removeprefix("W/").strip('"') for part in if_none_match.split(",")]:
        return Response(status_code=304, headers={"ETag": f'"{tag}"'})
    return JSONResponse(body, headers={"ETag": f'"{tag}"'})


def currents_out(item: ContentItem) -> dict:
    out = {"id": str(item.id)}
    out.update({field: item.data.get(field) for field in CURRENTS_FIELDS})
    out["domain"] = item.domain
    return out


def progress_out(progress: ContentProgress | None) -> dict:
    return {
        "position_seconds": progress.position_seconds if progress else None,
        "completed": bool(progress and progress.completed_at),
        "updated_at": iso(progress.updated_at) if progress else None,
    }


def load_currents(db: Session, item_id: uuid.UUID) -> ContentItem:
    item = db.scalar(published("currents").where(ContentItem.id == item_id))
    if item is None:
        raise ApiError(404, "not_found", "No Currents piece with that id.")
    return item


@router.get("/currents")
def list_currents(auth: Auth, db: DB, domain: str | None = None, if_none_match: Annotated[str | None, Header()] = None) -> Response:
    items = db.scalars(published("currents", domain).order_by(ContentItem.published_at.desc(), ContentItem.slug)).all()
    tag = etag([f"{item.id}:{item.version}" for item in items])
    return send({"items": [currents_out(item) for item in items]}, tag, if_none_match)


@router.get("/currents/{item_id}")
def get_currents(item_id: uuid.UUID, auth: Auth, db: DB, if_none_match: Annotated[str | None, Header()] = None) -> Response:
    user, _ = auth
    item = load_currents(db, item_id)
    progress = db.get(ContentProgress, (user.id, item.id))
    tag = etag([f"{item.id}:{item.version}", iso(progress.updated_at) if progress else ""])
    return send(currents_out(item) | {"progress": progress_out(progress)}, tag, if_none_match)


@router.put("/currents/{item_id}/progress")
def put_progress(item_id: uuid.UUID, body: ProgressPut, auth: Auth, db: DB) -> dict:
    user, _ = auth
    item = load_currents(db, item_id)
    progress = db.get(ContentProgress, (user.id, item.id))
    if progress is None:
        progress = ContentProgress(user_id=user.id, item_id=item.id)
        db.add(progress)
    progress.position_seconds = body.position_seconds
    if body.completed:
        progress.completed_at = progress.completed_at or now()
    else:
        progress.completed_at = None
    progress.updated_at = now()
    db.commit()
    return progress_out(progress)


@router.get("/library")
def list_library(
    auth: Auth,
    db: DB,
    kind: Literal["meal", "activity"] | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    query = select(ContentItem).where(ContentItem.published_at.is_not(None), ContentItem.retired_at.is_(None))
    query = query.where(ContentItem.type == kind) if kind else query.where(ContentItem.type.in_(("meal", "activity")))
    if q:
        query = query.where(ContentItem.data["name"].astext.ilike(f"%{q}%"))
    items = db.scalars(query.order_by(ContentItem.type, ContentItem.data["name"].astext, ContentItem.slug)).all()
    tag = etag([f"{item.id}:{item.version}" for item in items])
    body = {
        "items": [
            {
                "id": item.slug,
                "kind": item.type,
                "name": item.data.get("name"),
                "image_url": item.data.get("image_url"),
                "facts": item.data.get("facts", {}),
            }
            for item in items
        ]
    }
    return send(body, tag, if_none_match)


@router.get("/symptoms")
def list_symptoms(auth: Auth, db: DB, domain: str, if_none_match: Annotated[str | None, Header()] = None) -> Response:
    items = db.scalars(published("symptom", domain).order_by(ContentItem.data["position"].as_integer(), ContentItem.slug)).all()
    tag = etag([f"{item.id}:{item.version}" for item in items])
    body = {"domain": domain, "items": [{"name": item.data.get("name"), "body_map": bool(item.data.get("body_map"))} for item in items]}
    return send(body, tag, if_none_match)


@router.get("/glossary")
def list_glossary(auth: Auth, db: DB, if_none_match: Annotated[str | None, Header()] = None) -> Response:
    items = db.scalars(published("glossary").order_by(ContentItem.data["term"].astext, ContentItem.slug)).all()
    tag = etag([f"{item.id}:{item.version}" for item in items])
    return send({"items": [{"term": item.data.get("term"), "plain": item.data.get("plain")} for item in items]}, tag, if_none_match)
