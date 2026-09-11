from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging

from typing import Any

from fastapi import Body, FastAPI, File, Form, Header, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.bot.claim_messages import post_success_claim_for_validation
from app.bot.runtime import get_bot
from app.config import get_settings
from app.db import close_mongo_client, get_database
from app.services import (
    InvalidProfilePicture,
    add_user_secondary_class,
    create_success_claim,
    delete_user_picture,
    get_calendar_events,
    get_full_user_profile,
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
    parse_birthday,
    profile_picture_upload_directory,
    remove_user_secondary_class,
    update_user_birthday,
    update_user_class,
    update_user_picture,
    update_user_presentation,
    update_user_secondary_classes,
)
from app.services.user_service import (
    PROFILE_PICTURE_MAX_SIZE,
    PROFILE_PICTURE_SUPPORTED_TYPES,
    VALID_DOFUS_CLASSES,
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

settings = get_settings()
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
profile_picture_upload_directory().mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads/profile-pictures",
    StaticFiles(directory=profile_picture_upload_directory()),
    name="profile-pictures",
)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return _json_error(
        status.HTTP_400_BAD_REQUEST,
        "INVALID_REQUEST",
        "Request body or required field is invalid",
        exc.errors(),
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error", exc_info=exc)
    return _internal_error()


@app.get("/api/succes/unlock")
async def api_unlocked_successes(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if await get_user_by_token(token) is None:
        return _unauthorized()
    return JSONResponse(content=await get_unlocked_successes(token))


@app.get("/api/succes")
async def api_success_catalog(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    if await get_user_by_token(_extract_bearer_token(authorization)) is None:
        return _unauthorized()
    return JSONResponse(content=await get_success_catalog())


@app.get("/api/succes2")
async def api_success2_catalog(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    if await get_user_by_token(_extract_bearer_token(authorization)) is None:
        return _unauthorized()
    return JSONResponse(content=await get_success2_catalog())


@app.get("/api/succes/leaderboard")
async def api_success_leaderboard(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    if await get_user_by_token(_extract_bearer_token(authorization)) is None:
        return _unauthorized()
    return JSONResponse(content=await get_success_leaderboard())


@app.get("/api/succes/validations")
async def api_success_validations(authorization: str | None = Header(default=None)) -> JSONResponse:
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _unauthorized()

    history = await get_user_validation_history(str(user.get("discord_username", "")))
    return JSONResponse(status_code=status.HTTP_200_OK, content=history)


@app.get("/api/user")
async def api_user(authorization: str | None = Header(default=None)) -> JSONResponse:
    user = await get_user_profile(_extract_bearer_token(authorization))
    if user is None:
        return _unauthorized()

    return JSONResponse(status_code=status.HTTP_200_OK, content=user)


@app.post("/api/user/class")
async def api_user_class(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if await get_user_by_token(token) is None:
        return _unauthorized()

    class_name = payload.get("class")
    validation_error = _validate_class_name(class_name, "class")
    if validation_error is not None:
        return validation_error

    user = await update_user_class(token, class_name)
    if user is None:
        return _internal_error()

    return JSONResponse(status_code=status.HTTP_200_OK, content=user)


@app.get("/api/user/profile")
async def api_full_user_profile(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    profile = await get_full_user_profile(_extract_bearer_token(authorization))
    if profile is None:
        return _unauthorized()
    return JSONResponse(status_code=status.HTTP_200_OK, content=profile)


@app.get("/api/user/birthday")
async def api_user_birthday(authorization: str | None = Header(default=None)) -> JSONResponse:
    birthday_info = await get_user_birthday(_extract_bearer_token(authorization))
    if birthday_info is None:
        return _unauthorized()
    return JSONResponse(status_code=status.HTTP_200_OK, content=birthday_info)


@app.post("/api/user/birthday")
async def api_user_birthday_update(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if await get_user_by_token(token) is None:
        return _unauthorized()
    if "birthday" not in payload and "wish" not in payload:
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_REQUEST",
            "Missing required field: birthday or wish",
        )

    updates: dict[str, Any] = {}
    if "birthday" in payload:
        birthday = payload["birthday"]
        if birthday is not None and not isinstance(birthday, str):
            return _json_error(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_DATE",
                "Invalid date format. Use YYYY-MM-DD",
            )
        if isinstance(birthday, str):
            try:
                birthday_date = parse_birthday(birthday)
            except ValueError:
                return _json_error(
                    status.HTTP_400_BAD_REQUEST,
                    "INVALID_DATE",
                    "Invalid date format. Use YYYY-MM-DD",
                )
            if birthday_date >= datetime.now(timezone.utc).date():
                return _json_error(
                    status.HTTP_400_BAD_REQUEST,
                    "INVALID_DATE",
                    "Birthday must be a past date",
                )
        updates["birthday"] = birthday

    if "wish" in payload:
        wish = payload["wish"]
        if wish is not None and not isinstance(wish, str):
            return _json_error(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_REQUEST",
                "Wish must be a string or null",
            )
        if isinstance(wish, str) and len(wish) > 200:
            return _json_error(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_REQUEST",
                "Birthday wish cannot exceed 200 characters",
            )
        updates["wish"] = wish

    result = await update_user_birthday(token, **updates)
    if result is None:
        return _internal_error()
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.get("/api/user/presentation")
async def api_user_presentation(authorization: str | None = Header(default=None)) -> JSONResponse:
    presentation_info = await get_user_presentation(_extract_bearer_token(authorization))
    if presentation_info is None:
        return _unauthorized()
    return JSONResponse(status_code=status.HTTP_200_OK, content=presentation_info)


@app.post("/api/user/presentation")
async def api_user_presentation_update(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if await get_user_by_token(token) is None:
        return _unauthorized()
    if "presentation" not in payload:
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_REQUEST",
            "Missing required field: presentation",
        )

    presentation = payload["presentation"]
    if not isinstance(presentation, str):
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_REQUEST",
            "Presentation must be a string",
        )
    if len(presentation) > 2000:
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_REQUEST",
            "Presentation cannot exceed 2000 characters",
        )

    result = await update_user_presentation(token, presentation)
    if result is None:
        return _internal_error()
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.get("/api/user/classes")
async def api_user_classes(authorization: str | None = Header(default=None)) -> JSONResponse:
    classes_info = await get_user_classes(_extract_bearer_token(authorization))
    if classes_info is None:
        return _unauthorized()
    return JSONResponse(status_code=status.HTTP_200_OK, content=classes_info)


@app.post("/api/user/classes")
async def api_user_classes_update(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    current_user = await get_user_by_token(token)
    if current_user is None:
        return _unauthorized()
    if "secondary_classes" not in payload:
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_REQUEST",
            "Missing required field: secondary_classes",
        )

    secondary_classes = payload["secondary_classes"]
    if not isinstance(secondary_classes, list):
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_REQUEST",
            "secondary_classes must be an array",
        )
    for class_name in secondary_classes:
        validation_error = _validate_class_name(class_name, "secondary_classes")
        if validation_error is not None:
            return validation_error
    if current_user.get("class") in secondary_classes:
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_CLASS",
            "Main class cannot be included in secondary_classes",
        )

    result = await update_user_secondary_classes(token, secondary_classes)
    if result is None:
        return _internal_error()
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.post("/api/user/classes/add")
async def api_user_classes_add(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    current_user = await get_user_by_token(token)
    if current_user is None:
        return _unauthorized()
    if "class_name" not in payload:
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_REQUEST",
            "Missing required field: class_name",
        )
    class_name = payload["class_name"]
    validation_error = _validate_class_name(class_name, "class_name")
    if validation_error is not None:
        return validation_error
    if class_name == current_user.get("class"):
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_CLASS",
            "Main class cannot be added as a secondary class",
        )

    result = await add_user_secondary_class(token, class_name)
    if result is None:
        return _internal_error()
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.post("/api/user/classes/remove")
async def api_user_classes_remove(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if await get_user_by_token(token) is None:
        return _unauthorized()
    if "class_name" not in payload:
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_REQUEST",
            "Missing required field: class_name",
        )
    class_name = payload["class_name"]
    validation_error = _validate_class_name(class_name, "class_name")
    if validation_error is not None:
        return validation_error

    result = await remove_user_secondary_class(token, class_name)
    if result is None:
        return _internal_error()
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.get("/api/user/picture")
async def api_user_picture(authorization: str | None = Header(default=None)) -> JSONResponse:
    picture_info = await get_user_picture(_extract_bearer_token(authorization))
    if picture_info is None:
        return _unauthorized()
    return JSONResponse(status_code=status.HTTP_200_OK, content=picture_info)


@app.post("/api/user/picture")
async def api_user_picture_upload(
    picture: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if await get_user_by_token(token) is None:
        return _unauthorized()

    content_type = picture.content_type or ""
    if content_type not in PROFILE_PICTURE_SUPPORTED_TYPES:
        await picture.close()
        return _json_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_TYPE",
            "File type not supported. Use PNG, JPG, or JPEG",
        )
    file_content = await picture.read(PROFILE_PICTURE_MAX_SIZE + 1)
    if len(file_content) > PROFILE_PICTURE_MAX_SIZE:
        await picture.close()
        return _json_error(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "FILE_TOO_LARGE",
            "File size exceeds maximum limit of 5MB",
        )
    try:
        result = await update_user_picture(token, file_content, content_type)
    except InvalidProfilePicture:
        return _json_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_TYPE",
            "File type not supported. Use PNG, JPG, or JPEG",
        )
    finally:
        await picture.close()
    if result is None:
        return _internal_error()
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.delete("/api/user/picture")
async def api_user_picture_delete(authorization: str | None = Header(default=None)) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    if await get_user_by_token(token) is None:
        return _unauthorized()
    result = await delete_user_picture(token)
    if result is None:
        return _internal_error()
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.get("/api/succes2/total-tickets")
async def api_success2_total_tickets(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    if await get_user_by_token(_extract_bearer_token(authorization)) is None:
        return _unauthorized()
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
        return _unauthorized()

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
                return _json_error(
                    status.HTTP_400_BAD_REQUEST,
                    "Only PNG and JPG images are accepted",
                )
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


def _json_error(
    status_code: int,
    error: str,
    message: str | None = None,
    details: Any = None,
) -> JSONResponse:
    if message is None:
        message = error
        error = {
            status.HTTP_400_BAD_REQUEST: "INVALID_REQUEST",
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "FILE_TOO_LARGE",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "UNSUPPORTED_TYPE",
            status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_ERROR",
        }.get(status_code, "REQUEST_ERROR")
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {"error": error, "message": message, "details": details}
        ),
    )


def _unauthorized() -> JSONResponse:
    return _json_error(
        status.HTTP_401_UNAUTHORIZED,
        "UNAUTHORIZED",
        "Authentication token required",
    )


def _internal_error() -> JSONResponse:
    return _json_error(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred",
    )


def _validate_class_name(value: Any, field_name: str) -> JSONResponse | None:
    if not isinstance(value, str):
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_REQUEST",
            f"Missing or invalid required field: {field_name}",
        )
    if value not in VALID_DOFUS_CLASSES:
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_CLASS",
            f"Invalid class name. Must be one of: {', '.join(VALID_DOFUS_CLASSES)}",
        )
    return None
