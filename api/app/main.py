from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import auth, care_plans, chat, content, ehr, errors, files, journeys, logs, me, push, today, visits
from app.db import engine
from app.settings import settings

app = FastAPI(title="Rumi API", version="0.1.0")
errors.install(app)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(chat.router)
app.include_router(visits.router)
app.include_router(logs.router)
app.include_router(files.router)
app.include_router(content.router)
app.include_router(care_plans.router)
app.include_router(journeys.router)
app.include_router(journeys.habits_router)
app.include_router(push.router)
app.include_router(ehr.router)
app.include_router(ehr.integrations_router)
app.include_router(today.router)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception:
        return JSONResponse({"ok": False, "database": "down"}, status_code=503)
    return JSONResponse({"ok": True, "database": "ok"})
