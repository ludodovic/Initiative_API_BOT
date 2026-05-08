from contextlib import asynccontextmanager
import logging

from typing import Any

from fastapi import Body, FastAPI, File, Form, Header, UploadFile, status
from fastapi.responses import JSONResponse

from app.bot.claim_messages import post_success_claim_for_validation
from app.bot.runtime import get_bot
from app.db import close_mongo_client
from app.services import (
    create_success_claim,
    get_calendar_events,
    get_latest_newsletter,
    get_success_catalog,
    get_success_leaderboard,
    get_unlocked_successes,
    get_user_by_token,
    get_user_profile,
    update_user_class,
)
from app.services.claim_service import validate_image_content_types
from app.services.success_validation_service import find_success


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_mongo_client()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Initiative API",
    description="Frontend API for Initiative homepage news and user success progress.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/api/succes/unlock")
async def api_unlocked_successes(authorization: str | None = Header(default=None)) -> dict:
    return await get_unlocked_successes(_extract_bearer_token(authorization))


@app.get("/api/succes")
async def api_success_catalog() -> list[dict]:
    return await get_success_catalog()


@app.get("/api/succes/leaderboard")
async def api_success_leaderboard() -> list[dict]:
    return await get_success_leaderboard()


@app.get("/api/user")
async def api_user(authorization: str | None = Header(default=None)) -> JSONResponse:
    user = await get_user_profile(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    return JSONResponse(status_code=status.HTTP_200_OK, content=user)


@app.post("/api/user/class")
async def api_user_class(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    class_name = payload.get("class")
    if not isinstance(class_name, str):
        return _json_error(status.HTTP_400_BAD_REQUEST, "Class is required")

    user = await update_user_class(_extract_bearer_token(authorization), class_name)
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    return JSONResponse(status_code=status.HTTP_200_OK, content=user)


@app.post("/api/succes/claim")
async def api_claim_success(
    successId: str = Form(...),
    successName: str = Form(...),
    successDescription: str = Form(...),
    description: str = Form(default=""),
    images: list[UploadFile] | None = File(default=None),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    if not images:
        return _json_error(status.HTTP_400_BAD_REQUEST, "At least one image is required")

    selected_images = images[:3]
    content_types = [image.content_type or "" for image in selected_images]
    if not validate_image_content_types(content_types):
        return _json_error(status.HTTP_400_BAD_REQUEST, "Only PNG and JPG images are accepted")

    try:
        success_id = int(successId)
    except ValueError:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Unknown success")

    success = await find_success(str(success_id))
    if success is None:
        return _json_error(status.HTTP_404_NOT_FOUND, "Unknown success")

    try:
        image_payloads = [
            (image.content_type or "", await image.read())
            for image in selected_images
        ]
        claim = await create_success_claim(
            user=user,
            success_id=success_id,
            success_name=str(success["name"]),
            success_description=successDescription,
            description=description,
            images=image_payloads,
        )

        bot = get_bot()
        if bot is None:
            raise RuntimeError("Discord bot is not running in this process.")

        await post_success_claim_for_validation(bot, claim)
    except Exception as e:
        logger.info(f"Error occurred while creating claim: {e}")
        return _json_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to create claim")

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"ok": True, "claimId": claim["claimId"]},
    )


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


def _json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "message": message},
    )
