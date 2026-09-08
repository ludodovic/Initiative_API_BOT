from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from typing import Any

from PIL import Image, ImageOps

from app.config import get_settings
from app.db import get_database

# Valid Dofus class names as specified
VALID_DOFUS_CLASSES = [
    "Panda", "Iop", "Zobal", "Enu", "Feca", "Crâ", "Sacri",
    "Steam", "Forge", "Hupper", "Eca", "Xel", "Elio", "Roub",
    "Sram", "Sadi", "Eni", "Ougi", "Osa"
]

# Profile picture settings
PROFILE_PICTURE_MAX_SIZE = 5 * 1024 * 1024  # 5MB
PROFILE_PICTURE_SUPPORTED_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
}
PROFILE_PICTURE_MAX_DIMENSIONS = (1600, 1600)


async def get_user_profile(token: str | None) -> dict[str, str] | None:
    user = await get_user_by_token(token)
    if user is None:
        return None

    return _format_user_profile(user)


async def update_user_class(token: str | None, class_name: str) -> dict[str, str] | None:
    if not token:
        return None

    database = await get_database()
    user = await database["users"].find_one_and_update(
        {"token": token},
        {"$set": {"class": class_name}},
        return_document=True,
    )
    if user is None:
        return None

    return _format_user_profile(user)


async def get_user_by_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None

    database = await get_database()
    user = await database["users"].find_one({"token": token})
    return _serialize(user) if user else None


def _format_user_profile(user: dict[str, Any]) -> dict[str, str]:
    class_name = user.get("class")
    if not isinstance(class_name, str) or not class_name:
        class_name = "undefined"

    return {
        "dofus_username": str(user.get("dofus_username", "")),
        "class": class_name,
    }


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "_id"}


# Birthday service functions
async def get_user_birthday(token: str | None) -> dict[str, Any] | None:
    user = await get_user_by_token(token)
    if user is None:
        return None

    return {
        "birthday": user.get("birthday"),
        "wish": user.get("birthday_wish"),
    }


async def update_user_birthday(
    token: str | None,
    birthday: str | None = None,
    wish: str | None = None
) -> dict[str, Any] | None:
    if not token:
        return None

    # Validate birthday if provided
    if birthday is not None:
        if birthday and not _is_valid_iso_date(birthday):
            return None
        # Ensure past date only
        if birthday:
            try:
                date_obj = datetime.fromisoformat(birthday).date()
                today = datetime.now(timezone.utc).date()
                if date_obj > today:
                    return None  # Future date not allowed
            except ValueError:
                return None

    # Validate wish if provided
    if wish is not None and len(wish) > 200:
        return None

    database = await get_database()
    update_data = {}
    if birthday is not None:
        update_data["birthday"] = birthday
    if wish is not None:
        update_data["birthday_wish"] = wish

    user = await database["users"].find_one_and_update(
        {"token": token},
        {"$set": update_data},
        return_document=True,
    )

    if user is None:
        return None

    return {
        "birthday": user.get("birthday"),
        "wish": user.get("birthday_wish"),
        "message": "Birthday information updated",
    }


# Presentation service functions
async def get_user_presentation(token: str | None) -> dict[str, Any] | None:
    user = await get_user_by_token(token)
    if user is None:
        return None

    return {
        "presentation": user.get("presentation"),
    }


async def update_user_presentation(
    token: str | None,
    presentation: str
) -> dict[str, Any] | None:
    if not token:
        return None

    # Validate presentation length
    if len(presentation) > 2000:
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
        "presentation": presentation,
        "message": "Presentation updated",
    }


# Secondary classes service functions
async def get_user_classes(token: str | None) -> dict[str, Any] | None:
    user = await get_user_by_token(token)
    if user is None:
        return None

    main_class = user.get("class", "undefined")
    if not isinstance(main_class, str) or not main_class:
        main_class = "undefined"

    secondary_classes = user.get("secondary_classes")
    if not isinstance(secondary_classes, list):
        secondary_classes = []

    return {
        "main_class": main_class,
        "secondary_classes": secondary_classes,
    }


async def update_user_secondary_classes(
    token: str | None,
    secondary_classes: list[str]
) -> dict[str, Any] | None:
    if not token:
        return None

    # Validate all class names
    for class_name in secondary_classes:
        if class_name not in VALID_DOFUS_CLASSES:
            return None

    # Remove duplicates while preserving order
    seen = set()
    unique_classes = []
    for class_name in secondary_classes:
        if class_name not in seen:
            seen.add(class_name)
            unique_classes.append(class_name)
    secondary_classes = unique_classes

    database = await get_database()
    user = await database["users"].find_one({"token": token})
    if user is None:
        return None

    main_class = user.get("class", "undefined")
    if not isinstance(main_class, str) or not main_class:
        main_class = "undefined"

    # Ensure main class is not in secondary classes
    if main_class in secondary_classes:
        secondary_classes = [c for c in secondary_classes if c != main_class]

    updated_user = await database["users"].find_one_and_update(
        {"token": token},
        {"$set": {"secondary_classes": secondary_classes}},
        return_document=True,
    )

    if updated_user is None:
        return None

    return {
        "main_class": main_class,
        "secondary_classes": secondary_classes,
        "message": "Secondary classes updated",
    }


async def add_user_secondary_class(
    token: str | None,
    class_name: str
) -> dict[str, Any] | None:
    if not token:
        return None

    # Validate class name
    if class_name not in VALID_DOFUS_CLASSES:
        return None

    database = await get_database()
    user = await database["users"].find_one({"token": token})
    if user is None:
        return None

    main_class = user.get("class", "undefined")
    if not isinstance(main_class, str) or not main_class:
        main_class = "undefined"

    # Get existing secondary classes
    secondary_classes = user.get("secondary_classes")
    if not isinstance(secondary_classes, list):
        secondary_classes = []

    # Prevent duplicates
    if class_name in secondary_classes:
        return {
            "main_class": main_class,
            "secondary_classes": secondary_classes,
            "message": "Class already in secondary classes",
        }

    # Prevent main class from being added as secondary
    if class_name == main_class:
        return {
            "main_class": main_class,
            "secondary_classes": secondary_classes,
            "message": "Cannot add main class as secondary",
        }

    # Add the new class
    secondary_classes.append(class_name)

    updated_user = await database["users"].find_one_and_update(
        {"token": token},
        {"$set": {"secondary_classes": secondary_classes}},
        return_document=True,
    )

    if updated_user is None:
        return None

    return {
        "main_class": main_class,
        "secondary_classes": secondary_classes,
        "message": "Secondary class added",
    }


async def remove_user_secondary_class(
    token: str | None,
    class_name: str
) -> dict[str, Any] | None:
    if not token:
        return None

    database = await get_database()
    user = await database["users"].find_one({"token": token})
    if user is None:
        return None

    main_class = user.get("class", "undefined")
    if not isinstance(main_class, str) or not main_class:
        main_class = "undefined"

    # Get existing secondary classes
    secondary_classes = user.get("secondary_classes")
    if not isinstance(secondary_classes, list):
        secondary_classes = []

    # Remove the class if it exists
    if class_name in secondary_classes:
        secondary_classes = [c for c in secondary_classes if c != class_name]
        updated_user = await database["users"].find_one_and_update(
            {"token": token},
            {"$set": {"secondary_classes": secondary_classes}},
            return_document=True,
        )

        if updated_user is None:
            return None

        return {
            "main_class": main_class,
            "secondary_classes": secondary_classes,
            "message": "Secondary class removed",
        }
    else:
        return {
            "main_class": main_class,
            "secondary_classes": secondary_classes,
            "message": "Class not found in secondary classes",
        }


# Profile picture service functions
async def get_user_picture(token: str | None) -> dict[str, Any] | None:
    user = await get_user_by_token(token)
    if user is None:
        return None

    return {
        "picture_url": user.get("profile_picture_url"),
    }


async def update_user_picture(
    token: str | None,
    file_content: bytes,
    file_type: str
) -> dict[str, Any] | None:
    if not token:
        return None

    # Validate file type
    if file_type not in PROFILE_PICTURE_SUPPORTED_TYPES:
        return None

    # Validate file size
    if len(file_content) > PROFILE_PICTURE_MAX_SIZE:
        return None

    # Get user to get their ID for file naming
    user = await get_user_by_token(token)
    if user is None:
        return None

    user_id = user.get("id")
    if not isinstance(user_id, int):
        return None

    # Delete old picture if it exists
    old_picture_url = user.get("profile_picture_url")
    if old_picture_url:
        await _delete_profile_picture_file(old_picture_url)

    # Store the new picture
    try:
        picture_url = await _store_profile_picture(user_id, file_content, file_type)
    except Exception:
        return None

    database = await get_database()
    updated_user = await database["users"].find_one_and_update(
        {"token": token},
        {"$set": {"profile_picture_url": picture_url}},
        return_document=True,
    )

    if updated_user is None:
        return None

    return {
        "picture_url": picture_url,
        "message": "Profile picture updated successfully",
    }


async def delete_user_picture(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None

    database = await get_database()
    user = await database["users"].find_one({"token": token})
    if user is None:
        return None

    # Delete the file if it exists
    old_picture_url = user.get("profile_picture_url")
    if old_picture_url:
        await _delete_profile_picture_file(old_picture_url)

    # Remove the URL from the user
    updated_user = await database["users"].find_one_and_update(
        {"token": token},
        {"$unset": {"profile_picture_url": ""}},
        return_document=True,
    )

    if updated_user is None:
        return None

    return {
        "message": "Profile picture removed successfully",
    }


# Helper functions
def _is_valid_iso_date(date_str: str) -> bool:
    """Check if string is a valid ISO date format (YYYY-MM-DD)."""
    try:
        datetime.fromisoformat(date_str)
        return True
    except ValueError:
        return False


def _store_profile_picture(user_id: int, file_content: bytes, file_type: str) -> str:
    """Store profile picture and return the URL/path."""
    settings = get_settings()
    upload_dir = Path(settings.profile_picture_upload_dir)
    user_dir = upload_dir / f"user_{user_id}"
    user_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    file_extension = PROFILE_PICTURE_SUPPORTED_TYPES[file_type]
    filename = f"profile_{uuid4().hex}.{file_extension}"
    file_path = user_dir / filename

    # Process and save the image
    with Image.open(BytesIO(file_content)) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail(PROFILE_PICTURE_MAX_DIMENSIONS)
        if file_extension == "jpg":
            image = image.convert("RGB")
            image.save(file_path, "JPEG", quality=85, optimize=True)
        else:
            image.save(file_path, "PNG", optimize=True)

    return str(file_path)


async def _delete_profile_picture_file(picture_url: str) -> None:
    """Delete a profile picture file if it exists."""
    try:
        Path(picture_url).unlink(missing_ok=True)
        # Also try to remove the user directory if it's empty
        user_dir = Path(picture_url).parent
        if user_dir.exists() and not list(user_dir.iterdir()):
            user_dir.rmdir()
    except Exception:
        pass  # Silently ignore file deletion errors


# Total tickets for season 2 (optional)
async def get_total_season2_tickets() -> dict[str, Any]:
    database = await get_database()
    successes = database["succes2"].find({}, {"_id": 0, "difficulte": 1})
    
    total = 0
    async for success in successes:
        difficulte = success.get("difficulte")
        if isinstance(difficulte, str):
            total += len(difficulte)
    
    return {"total": total}
