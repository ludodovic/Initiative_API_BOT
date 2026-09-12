from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings
from app.db import get_database


VALID_DOFUS_CLASSES = [
    "Panda", "Iop", "Zobal", "Enu", "Feca", "Crâ", "Sacri", "Steam",
    "Forge", "Hupper", "Eca", "Xel", "Elio", "Roub", "Sram", "Sadi",
    "Eni", "Ougi", "Osa",
]
DISPLAYABLE_GUILD_ROLES = ("Initiateur", "Assemblée", "Conseiller")

PUBLIC_PROFILE_PROJECTION = {
    "_id": 0,
    "dofus_username": 1,
    "class": 1,
    "profile_picture_url": 1,
    "birthday": 1,
    "birthday_wish": 1,
    "presentation": 1,
    "secondary_classes": 1,
    "roles": 1,
}

PROFILE_PICTURE_MAX_SIZE = 5 * 1024 * 1024
PROFILE_PICTURE_SUPPORTED_TYPES = {"image/png": "png", "image/jpeg": "jpg"}
PROFILE_PICTURE_MAX_DIMENSIONS = (1600, 1600)
PROFILE_PICTURE_PUBLIC_PATH = "/uploads/profile-pictures"
_UNSET = object()


class InvalidProfilePicture(ValueError):
    """Raised when uploaded bytes are not a supported, decodable image."""


async def get_user_profile(token: str | None) -> dict[str, str] | None:
    user = await get_user_by_token(token)
    return _format_user_profile(user) if user is not None else None


async def get_full_user_profile(token: str | None) -> dict[str, Any] | None:
    user = await get_user_by_token(token)
    if user is None:
        return None

    profile: dict[str, Any] = _format_user_profile(user)
    profile.update(
        {
            "picture_url": _public_picture_url(user.get("profile_picture_url")),
            "birthday": _format_birthday(user.get("birthday")),
            "wish": user.get("birthday_wish"),
            "presentation": user.get("presentation"),
            "secondary_classes": _clean_stored_classes(
                user.get("secondary_classes"), profile["class"]
            ),
        }
    )
    return profile


async def update_user_class(token: str | None, class_name: str) -> dict[str, str] | None:
    if not token or class_name not in VALID_DOFUS_CLASSES:
        return None

    database = await get_database()
    user = await database["users"].find_one_and_update(
        {"token": token},
        {"$set": {"class": class_name}, "$pull": {"secondary_classes": class_name}},
        return_document=True,
    )
    return _format_user_profile(user) if user is not None else None


async def get_user_by_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    database = await get_database()
    user = await database["users"].find_one({"token": token})
    return _serialize(user) if user else None


def can_view_player_profiles(user: dict[str, Any]) -> bool:
    roles = user.get("roles")
    return isinstance(roles, list) and any(
        role in DISPLAYABLE_GUILD_ROLES for role in roles
    )


async def list_displayable_profiles() -> list[dict[str, Any]]:
    database = await get_database()
    cursor = database["users"].find(
        {
            "presentation": {"$type": "string", "$regex": r"\S"},
            "class": {"$type": "string", "$regex": r"\S"},
        },
        PUBLIC_PROFILE_PROJECTION,
    ).sort("dofus_username", 1)
    return [_format_public_profile(user) async for user in cursor]


async def get_player_profile(dofus_username: str) -> dict[str, Any] | None:
    database = await get_database()
    user = await database["users"].find_one(
        {"dofus_username": dofus_username}, PUBLIC_PROFILE_PROJECTION
    )
    return _format_public_profile(user) if user is not None else None


async def get_user_birthday(token: str | None) -> dict[str, Any] | None:
    user = await get_user_by_token(token)
    if user is None:
        return None
    return {
        "birthday": _format_birthday(user.get("birthday")),
        "wish": user.get("birthday_wish"),
    }


async def update_user_birthday(
    token: str | None,
    birthday: str | None | object = _UNSET,
    wish: str | None | object = _UNSET,
) -> dict[str, Any] | None:
    if not token:
        return None
    if birthday is not _UNSET and birthday is not None:
        if not isinstance(birthday, str):
            return None
        try:
            birthday_date = parse_birthday(birthday)
        except ValueError:
            return None
        if birthday_date >= datetime.now(timezone.utc).date():
            return None
    if wish is not _UNSET and wish is not None:
        if not isinstance(wish, str) or len(wish) > 200:
            return None

    update_data: dict[str, Any] = {}
    if birthday is not _UNSET:
        update_data["birthday"] = birthday
    if wish is not _UNSET:
        update_data["birthday_wish"] = wish

    database = await get_database()
    user = await database["users"].find_one_and_update(
        {"token": token}, {"$set": update_data}, return_document=True
    )
    if user is None:
        return None
    return {
        "birthday": _format_birthday(user.get("birthday")),
        "wish": user.get("birthday_wish"),
        "message": "Birthday information updated",
    }


async def get_user_presentation(token: str | None) -> dict[str, Any] | None:
    user = await get_user_by_token(token)
    return {"presentation": user.get("presentation")} if user is not None else None


async def update_user_presentation(
    token: str | None, presentation: str
) -> dict[str, Any] | None:
    if not token or not isinstance(presentation, str) or len(presentation) > 2000:
        return None
    database = await get_database()
    user = await database["users"].find_one_and_update(
        {"token": token},
        {"$set": {"presentation": presentation}},
        return_document=True,
    )
    if user is None:
        return None
    return {
        "presentation": user.get("presentation", presentation),
        "message": "Presentation updated",
    }


async def get_user_classes(token: str | None) -> dict[str, Any] | None:
    user = await get_user_by_token(token)
    if user is None:
        return None
    main_class = _main_class(user)
    return {
        "main_class": main_class,
        "secondary_classes": _clean_stored_classes(user.get("secondary_classes"), main_class),
    }


async def update_user_secondary_classes(
    token: str | None, secondary_classes: list[str]
) -> dict[str, Any] | None:
    if (
        not token
        or not isinstance(secondary_classes, list)
        or any(name not in VALID_DOFUS_CLASSES for name in secondary_classes)
    ):
        return None
    database = await get_database()
    user = await database["users"].find_one({"token": token})
    if user is None:
        return None

    main_class = _main_class(user)
    normalized = [
        name for name in _unique_classes(secondary_classes) if name != main_class
    ]
    updated = await database["users"].find_one_and_update(
        {"token": token},
        {"$set": {"secondary_classes": normalized}},
        return_document=True,
    )
    if updated is None:
        return None
    return {
        "main_class": main_class,
        "secondary_classes": normalized,
        "message": "Secondary classes updated",
    }


async def add_user_secondary_class(
    token: str | None, class_name: str
) -> dict[str, Any] | None:
    if not token or class_name not in VALID_DOFUS_CLASSES:
        return None
    database = await get_database()
    user = await database["users"].find_one({"token": token})
    if user is None:
        return None

    main_class = _main_class(user)
    secondary_classes = _clean_stored_classes(user.get("secondary_classes"), main_class)
    if class_name == main_class:
        message = "Cannot add main class as secondary"
    elif class_name in secondary_classes:
        message = "Class already in secondary classes"
    else:
        updated = await database["users"].find_one_and_update(
            {"token": token, "class": {"$ne": class_name}},
            {"$addToSet": {"secondary_classes": class_name}},
            return_document=True,
        )
        if updated is None:
            return None
        main_class = _main_class(updated)
        secondary_classes = _clean_stored_classes(
            updated.get("secondary_classes"), main_class
        )
        message = "Secondary class added"

    return {
        "main_class": main_class,
        "secondary_classes": secondary_classes,
        "message": message,
    }


async def remove_user_secondary_class(
    token: str | None, class_name: str
) -> dict[str, Any] | None:
    if not token or class_name not in VALID_DOFUS_CLASSES:
        return None
    database = await get_database()
    user = await database["users"].find_one_and_update(
        {"token": token},
        {"$pull": {"secondary_classes": class_name}},
        return_document=True,
    )
    if user is None:
        return None
    main_class = _main_class(user)
    return {
        "main_class": main_class,
        "secondary_classes": _clean_stored_classes(user.get("secondary_classes"), main_class),
        "message": "Secondary class removed",
    }


async def get_user_picture(token: str | None) -> dict[str, Any] | None:
    user = await get_user_by_token(token)
    return (
        {"picture_url": _public_picture_url(user.get("profile_picture_url"))}
        if user is not None
        else None
    )


async def update_user_picture(
    token: str | None, file_content: bytes, file_type: str
) -> dict[str, Any] | None:
    if not token:
        return None
    user = await get_user_by_token(token)
    if user is None or not isinstance(user.get("id"), int):
        return None

    picture_url, picture_path = _store_profile_picture(user["id"], file_content, file_type)
    database = await get_database()
    try:
        updated = await database["users"].find_one_and_update(
            {"token": token},
            {"$set": {"profile_picture_url": picture_url}},
            return_document=True,
        )
    except Exception:
        picture_path.unlink(missing_ok=True)
        raise
    if updated is None:
        picture_path.unlink(missing_ok=True)
        return None

    old_picture_url = user.get("profile_picture_url")
    if isinstance(old_picture_url, str) and old_picture_url != picture_url:
        _delete_profile_picture_file(old_picture_url)
    return {
        "picture_url": _public_picture_url(picture_url),
        "message": "Profile picture updated successfully",
    }


async def delete_user_picture(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    database = await get_database()
    user = await database["users"].find_one_and_update(
        {"token": token},
        {"$unset": {"profile_picture_url": ""}},
        return_document=False,
    )
    if user is None:
        return None
    old_picture_url = user.get("profile_picture_url")
    if isinstance(old_picture_url, str):
        _delete_profile_picture_file(old_picture_url)
    return {"message": "Profile picture removed successfully"}


async def get_total_season2_tickets(
    token: str | None,
) -> dict[str, int] | None:
    if not token:
        return None

    database = await get_database()
    user = await database["users"].find_one(
        {"token": token}, {"_id": 0, "bonus_ticket_count": 1}
    )
    if user is None:
        return None

    successes = database["succes2"].find({}, {"_id": 0, "difficulte": 1})
    total = 0
    async for success in successes:
        difficulty = success.get("difficulte")
        if isinstance(difficulty, str):
            total += len(difficulty)

    bonus_ticket_count = user.get("bonus_ticket_count")
    if isinstance(bonus_ticket_count, int) and not isinstance(
        bonus_ticket_count, bool
    ):
        total += bonus_ticket_count
    return {"total": total}


def profile_picture_upload_directory() -> Path:
    return Path(get_settings().profile_picture_upload_dir).resolve()


def parse_birthday(value: str) -> date:
    """Parse exactly YYYY-MM-DD, rejecting timestamps and non-padded dates."""
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Birthday must use YYYY-MM-DD")
    return parsed


def _format_user_profile(user: dict[str, Any]) -> dict[str, str]:
    return {
        "dofus_username": str(user.get("dofus_username", "")),
        "class": _main_class(user),
    }


def _format_public_profile(user: dict[str, Any]) -> dict[str, Any]:
    class_name = user.get("class")
    if not isinstance(class_name, str) or not class_name.strip():
        class_name = None

    presentation = user.get("presentation")
    if not isinstance(presentation, str):
        presentation = None

    wish = user.get("birthday_wish")
    if not isinstance(wish, str):
        wish = None

    stored_roles = user.get("roles")
    if not isinstance(stored_roles, list):
        stored_roles = []
    roles = [role for role in DISPLAYABLE_GUILD_ROLES if role in stored_roles]

    return {
        "dofus_username": str(user.get("dofus_username", "")),
        "class": class_name,
        "profile_picture_url": _public_picture_url(
            user.get("profile_picture_url")
        ),
        "birthday": _format_birthday(user.get("birthday")),
        "wish": wish,
        "presentation": presentation,
        "secondary_classes": _clean_stored_classes(
            user.get("secondary_classes"), class_name or ""
        ),
        "roles": roles,
    }


def _main_class(user: dict[str, Any]) -> str:
    class_name = user.get("class")
    return class_name if isinstance(class_name, str) and class_name else "undefined"


def _unique_classes(classes: list[str]) -> list[str]:
    return list(dict.fromkeys(classes))


def _clean_stored_classes(value: Any, main_class: str) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique_classes(
        [
            name for name in value
            if isinstance(name, str)
            and name in VALID_DOFUS_CLASSES
            and name != main_class
        ]
    )


def _format_birthday(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value if isinstance(value, str) else None


def _public_picture_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value.startswith(("https://", "http://")):
        return value
    if value.startswith(f"{PROFILE_PICTURE_PUBLIC_PATH}/"):
        relative_url = value
    else:
        legacy_path = Path(value)
        try:
            relative_path = legacy_path.resolve().relative_to(
                profile_picture_upload_directory()
            )
        except ValueError:
            return None
        relative_url = f"{PROFILE_PICTURE_PUBLIC_PATH}/{relative_path.as_posix()}"

    public_base_url = get_settings().api_public_url.rstrip("/")
    return f"{public_base_url}{relative_url}" if public_base_url else relative_url


def _store_profile_picture(
    user_id: int, file_content: bytes, file_type: str
) -> tuple[str, Path]:
    if not file_content or len(file_content) > PROFILE_PICTURE_MAX_SIZE:
        raise InvalidProfilePicture("Invalid profile picture size")
    expected_extension = PROFILE_PICTURE_SUPPORTED_TYPES.get(file_type)
    if expected_extension is None:
        raise InvalidProfilePicture("Unsupported profile picture type")

    file_path: Path | None = None
    try:
        with Image.open(BytesIO(file_content)) as image:
            actual_format = image.format
            width, height = image.size
            if width * height > 25_000_000:
                raise InvalidProfilePicture("Profile picture dimensions are too large")
            image.verify()
        if actual_format not in {"PNG", "JPEG"}:
            raise InvalidProfilePicture("Unsupported profile picture type")
        if (actual_format == "PNG") != (expected_extension == "png"):
            raise InvalidProfilePicture("File content does not match its media type")

        upload_dir = profile_picture_upload_directory()
        user_dir = upload_dir / f"user_{user_id}"
        user_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(datetime.now(timezone.utc).timestamp())
        filename = f"user_{user_id}_{timestamp}_{uuid4().hex}.{expected_extension}"
        file_path = user_dir / filename

        with Image.open(BytesIO(file_content)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(PROFILE_PICTURE_MAX_DIMENSIONS)
            if expected_extension == "jpg":
                image.convert("RGB").save(file_path, "JPEG", quality=85, optimize=True)
            else:
                image.save(file_path, "PNG", optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if file_path is not None:
            file_path.unlink(missing_ok=True)
        raise InvalidProfilePicture("Uploaded file is not a valid PNG or JPEG") from exc

    picture_url = f"{PROFILE_PICTURE_PUBLIC_PATH}/user_{user_id}/{filename}"
    return picture_url, file_path


def _delete_profile_picture_file(picture_url: str) -> None:
    upload_dir = profile_picture_upload_directory()
    if picture_url.startswith(f"{PROFILE_PICTURE_PUBLIC_PATH}/"):
        relative_path = Path(picture_url.removeprefix(f"{PROFILE_PICTURE_PUBLIC_PATH}/"))
        candidates = [(upload_dir / relative_path).resolve()]
    else:
        relative_path = Path(picture_url)
        candidates = [relative_path.resolve()]
        if not relative_path.is_absolute():
            candidates.append((upload_dir / relative_path).resolve())

    candidate = next(
        (
            path
            for path in candidates
            if _is_path_within(path, upload_dir)
        ),
        None,
    )
    if candidate is None:
        return

    candidate.unlink(missing_ok=True)
    user_dir = candidate.parent
    if user_dir != upload_dir and user_dir.exists() and not any(user_dir.iterdir()):
        user_dir.rmdir()


def _is_path_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "_id"}
