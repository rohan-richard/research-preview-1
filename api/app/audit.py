import ipaddress
import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth import DB, Auth
from app.models import AuditLog, User


def record(
    db: Session,
    *,
    actor: User | None,
    user_id: uuid.UUID,
    action: str,
    resource: str,
    resource_id: uuid.UUID | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_type="user" if actor else "system",
            actor_id=actor.id if actor else None,
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            ip=ip,
        )
    )


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    host = forwarded.split(",")[0].strip() or (request.client.host if request.client else "")
    # The header comes from outside, so a value that is not an address becomes null instead of a database error.
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


class Recorder:
    def __init__(self, request: Request, auth: Auth, db: DB):
        self.db = db
        self.user = auth[0]
        self.ip = client_ip(request)

    def record(self, action: str, resource: str, resource_id: uuid.UUID | None = None) -> None:
        record(self.db, actor=self.user, user_id=self.user.id, action=action, resource=resource, resource_id=resource_id, ip=self.ip)


Audit = Annotated[Recorder, Depends()]
