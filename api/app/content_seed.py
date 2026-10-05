import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.clock import now
from app.db import SessionLocal
from app.models import ContentItem

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


def read_items(folder: Path = CONTENT_DIR) -> list[dict]:
    items = []
    for path in sorted(folder.glob("*.json")):
        for item in json.loads(path.read_text()):
            items.append(
                {
                    "type": item["type"],
                    "slug": item["slug"],
                    "domain": item.get("domain"),
                    "locale": item.get("locale", "en-US"),
                    "version": item.get("version", 1),
                    "data": item["data"],
                }
            )
    return items


def load(db: Session, folder: Path = CONTENT_DIR) -> dict[str, int]:
    items = read_items(folder)
    before = set(db.scalars(select(ContentItem.id)))
    stamp = now()
    for item in items:
        statement = insert(ContentItem).values(published_at=stamp, **item)
        statement = statement.on_conflict_do_update(
            index_elements=["type", "slug", "locale"],
            set_={"domain": statement.excluded.domain, "version": statement.excluded.version, "data": statement.excluded.data},
        )
        db.execute(statement)
    db.flush()
    after = set(db.scalars(select(ContentItem.id)))
    inserted = len(after - before)
    return {"read": len(items), "inserted": inserted, "updated": len(items) - inserted}


def main() -> None:
    with SessionLocal() as db:
        counts = load(db)
        db.commit()
    print(f"content: {counts['read']} items read, {counts['inserted']} inserted, {counts['updated']} updated")


if __name__ == "__main__":
    main()
