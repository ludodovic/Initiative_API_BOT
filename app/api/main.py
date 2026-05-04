from contextlib import asynccontextmanager

from fastapi import FastAPI, Header

from app.db import close_mongo_client
from app.services import get_calendar_events, get_latest_newsletter, get_unlocked_successes


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_mongo_client()


app = FastAPI(
    title="Initiative API",
    description="Frontend API for Initiative homepage news and user success progress.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/api/succes/unlock")
async def api_unlocked_successes(authorization: str | None = Header(default=None)) -> dict:
    return await get_unlocked_successes(_extract_bearer_token(authorization))


@app.get("/api/news/calendar")
async def api_calendar_events() -> list[dict[str, str]]:
    return await get_calendar_events()


@app.get("/api/news/letter")
async def api_latest_newsletter() -> dict[str, str]:
    return await get_latest_newsletter()


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()
