from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging

from typing import Any

from fastapi import Body, FastAPI, File, Form, Header, UploadFile, status
from fastapi.responses import JSONResponse

from app.bot.claim_messages import post_success_claim_for_validation
from app.bot.runtime import get_bot
from app.db import close_mongo_client, get_database
from app.services import (
    add_user_secondary_class,
    create_success_claim,
    delete_user_picture,
    get_calendar_events,
    get_latest_newsletter,
    get_success2_catalog,
    get_success_catalog,
    get_success_leaderboard,
    get_total_season2_tickets,
    get_unlocked_successes,
    get_user_birthday,
    get_user_by_token,
    get_user_classes,
    get_user_picture,
    get_user_presentation,
    get_user_profile,
    get_user_validation_history,
    remove_user_secondary_class,
    update_user_birthday,
    update_user_class,
    update_user_picture,
    update_user_presentation,
    update_user_secondary_classes,
)
from app.services.user_service import VALID_DOFUS_CLASSES, PROFILE_PICTURE_SUPPORTED_TYPES, PROFILE_PICTURE_MAX_SIZE
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


@app.get("/api/succes2")
async def api_success2_catalog() -> list[dict]:
    return await get_success2_catalog()


@app.get("/api/succes/leaderboard")
async def api_success_leaderboard() -> list[dict]:
    return await get_success_leaderboard()


@app.get("/api/succes/validations")
async def api_success_validations(authorization: str | None = Header(default=None)) -> JSONResponse:
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    history = await get_user_validation_history(str(user.get("discord_username", "")))
    return JSONResponse(status_code=status.HTTP_200_OK, content=history)


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


# Birthday endpoints
@app.get("/api/user/birthday")
async def api_user_birthday(authorization: str | None = Header(default=None)) -> JSONResponse:
    birthday_info = await get_user_birthday(_extract_bearer_token(authorization))
    if birthday_info is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    return JSONResponse(status_code=status.HTTP_200_OK, content=birthday_info)


@app.post("/api/user/birthday")
async def api_user_birthday_update(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if token is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    birthday = payload.get("birthday")
    wish = payload.get("wish")

    # Validate birthday format if provided
    if birthday is not None and birthday:
        if not isinstance(birthday, str):
            return _json_error(status.HTTP_400_BAD_REQUEST, "Birthday must be a string in YYYY-MM-DD format")
        try:
            datetime.fromisoformat(birthday)
        except ValueError:
            return _json_error(status.HTTP_400_BAD_REQUEST, "Invalid date format. Use YYYY-MM-DD")
        
        # Validate it's a past date
        try:
            date_obj = datetime.fromisoformat(birthday).date()
            today = datetime.now(timezone.utc).date()
            if date_obj > today:
                return _json_error(status.HTTP_400_BAD_REQUEST, "Birthday cannot be in the future")
        except ValueError:
            return _json_error(status.HTTP_400_BAD_REQUEST, "Invalid date format. Use YYYY-MM-DD")

    # Validate wish length if provided
    if wish is not None and len(wish) > 200:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Birthday wish cannot exceed 200 characters")

    result = await update_user_birthday(token, birthday, wish)
    if result is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Invalid birthday or wish data")

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


# Presentation endpoints
@app.get("/api/user/presentation")
async def api_user_presentation(authorization: str | None = Header(default=None)) -> JSONResponse:
    presentation_info = await get_user_presentation(_extract_bearer_token(authorization))
    if presentation_info is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    return JSONResponse(status_code=status.HTTP_200_OK, content=presentation_info)


@app.post("/api/user/presentation")
async def api_user_presentation_update(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if token is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    presentation = payload.get("presentation")
    if presentation is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Presentation text is required")
    
    if not isinstance(presentation, str):
        return _json_error(status.HTTP_400_BAD_REQUEST, "Presentation must be a string")
    
    if len(presentation) > 2000:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Presentation cannot exceed 2000 characters")

    result = await update_user_presentation(token, presentation)
    if result is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Invalid presentation data")

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


# Classes endpoints
@app.get("/api/user/classes")
async def api_user_classes(authorization: str | None = Header(default=None)) -> JSONResponse:
    classes_info = await get_user_classes(_extract_bearer_token(authorization))
    if classes_info is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    return JSONResponse(status_code=status.HTTP_200_OK, content=classes_info)


@app.post("/api/user/classes")
async def api_user_classes_update(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if token is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    secondary_classes = payload.get("secondary_classes")
    if secondary_classes is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "secondary_classes is required")
    
    if not isinstance(secondary_classes, list):
        return _json_error(status.HTTP_400_BAD_REQUEST, "secondary_classes must be an array")

    # Validate all class names
    for class_name in secondary_classes:
        if not isinstance(class_name, str):
            return _json_error(status.HTTP_400_BAD_REQUEST, f"Invalid class name: {class_name}. Must be a string")
        if class_name not in VALID_DOFUS_CLASSES:
            return _json_error(status.HTTP_400_BAD_REQUEST, f"Invalid class name: {class_name}. Must be one of: {', '.join(VALID_DOFUS_CLASSES)}")

    result = await update_user_secondary_classes(token, secondary_classes)
    if result is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Invalid secondary classes data")

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.post("/api/user/classes/add")
async def api_user_classes_add(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if token is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    class_name = payload.get("class_name")
    if class_name is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "class_name is required")
    
    if not isinstance(class_name, str):
        return _json_error(status.HTTP_400_BAD_REQUEST, "class_name must be a string")

    # Validate class name
    if class_name not in VALID_DOFUS_CLASSES:
        return _json_error(status.HTTP_400_BAD_REQUEST, f"Invalid class name: {class_name}. Must be one of: {', '.join(VALID_DOFUS_CLASSES)}")

    result = await add_user_secondary_class(token, class_name)
    if result is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Invalid class data")

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.post("/api/user/classes/remove")
async def api_user_classes_remove(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if token is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    class_name = payload.get("class_name")
    if class_name is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "class_name is required")
    
    if not isinstance(class_name, str):
        return _json_error(status.HTTP_400_BAD_REQUEST, "class_name must be a string")

    result = await remove_user_secondary_class(token, class_name)
    if result is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Invalid class data")

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


# Profile picture endpoints
@app.get("/api/user/picture")
async def api_user_picture(authorization: str | None = Header(default=None)) -> JSONResponse:
    picture_info = await get_user_picture(_extract_bearer_token(authorization))
    if picture_info is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    return JSONResponse(status_code=status.HTTP_200_OK, content=picture_info)


@app.post("/api/user/picture")
async def api_user_picture_upload(
    picture: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if token is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    # Validate file type
    content_type = picture.content_type or ""
    if content_type not in PROFILE_PICTURE_SUPPORTED_TYPES:
        return _json_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"File type not supported. Use PNG, JPG, or JPEG. Got: {content_type}"
        )

    # Check file size by reading content
    file_content = await picture.read()
    if len(file_content) > PROFILE_PICTURE_MAX_SIZE:
        return _json_error(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "File size exceeds maximum limit of 5MB"
        )

    result = await update_user_picture(token, file_content, content_type)
    if result is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Unable to process profile picture")

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.delete("/api/user/picture")
async def api_user_picture_delete(authorization: str | None = Header(default=None)) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if token is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    result = await delete_user_picture(token)
    if result is None:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Unable to delete profile picture")

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


# Total season 2 tickets endpoint (optional)
@app.get("/api/succes2/total-tickets")
async def api_success2_total_tickets() -> JSONResponse:
    result = await get_total_season2_tickets()
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


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

    try:
        success_id = int(successId)
    except ValueError:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Unknown success")

    success_saisson = 1
    success = await find_success(str(success_id))
    if success is None:
        success_saisson = 2
        database = await get_database()
        success = await database["succes2"].find_one({"id": success_id})
        if success is None:
            return _json_error(status.HTTP_404_NOT_FOUND, "Unknown success")

    try:
        if success_saisson == 2 and not images:
            if images is None or len(images) == 0:
                image_payloads = []
        else:
            if not images:
                return _json_error(status.HTTP_400_BAD_REQUEST, "At least one image is required")
            selected_images = images[:3]
            content_types = [image.content_type or "" for image in selected_images]
            if not validate_image_content_types(content_types):
                return _json_error(status.HTTP_400_BAD_REQUEST, "Only PNG and JPG images are accepted")
            image_payloads = [
                (image.content_type or "", await image.read())
                for image in selected_images
            ]

        claim = await create_success_claim(
            user=user,
            success_id=success_id,
            success_name=successName,
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
