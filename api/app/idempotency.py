from typing import Annotated

from fastapi import Depends, Header, Request, Response

from app.auth import DB, Auth
from app.errors import ApiError
from app.models import IdempotencyKey


class Idempotency:
    def __init__(
        self,
        request: Request,
        response: Response,
        auth: Auth,
        db: DB,
        idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
    ):
        self.db = db
        self.response = response
        self.user_id = auth[0].id
        self.key = idempotency_key
        # The route template, not the URL, so a key covers one route whatever ids are in the path.
        self.route = f"{request.method} {request.scope['route'].path}"

    def replay(self) -> dict | None:
        if not self.key:
            return None
        stored = self.db.get(IdempotencyKey, (self.user_id, self.key))
        if stored is None:
            return None
        if stored.route != self.route:
            raise ApiError(400, "invalid_request", "Idempotency-Key was already used for another route.")
        self.response.status_code = stored.response["status"]
        return stored.response["body"]

    def store(self, status: int, body: dict) -> None:
        if self.key:
            self.db.add(IdempotencyKey(user_id=self.user_id, key=self.key, route=self.route, response={"status": status, "body": body}))


Idempotent = Annotated[Idempotency, Depends()]
