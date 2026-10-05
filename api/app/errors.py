from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": {"code": exc.code, "message": exc.message, **exc.extra}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = first.get("msg", "The request is not valid.")
        if where:
            message = f"{where}: {message}"
        return JSONResponse({"error": {"code": "invalid_request", "message": message}}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = {401: "access_token_invalid", 404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "error")
        return JSONResponse({"error": {"code": code, "message": str(exc.detail)}}, status_code=exc.status_code, headers=exc.headers)
