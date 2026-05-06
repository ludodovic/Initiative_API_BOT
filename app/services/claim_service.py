from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageOps

from app.config import get_settings
from app.db import get_database

CLAIM_COLLECTION = "success_claims"
MAX_IMAGES = 3
MAX_IMAGE_SIZE = (1600, 1600)
SUPPORTED_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
}


async def get_user_by_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None

    database = await get_database()
    user = await database["users"].find_one({"token": token})
    return _serialize(user) if user else None


async def create_success_claim(
    user: dict[str, Any],
    success_id: int,
    success_name: str,
    success_description: str,
    description: str,
    images: list[tuple[str, bytes]],
) -> dict[str, Any]:
    claim_id = f"claim_{uuid4().hex}"
    image_paths = _store_images(claim_id, images[:MAX_IMAGES])
    now = datetime.now(UTC)

    claim = {
        "claimId": claim_id,
        "user": {
            "id": user.get("id"),
            "discord_username": user.get("discord_username"),
            "dofus_username": user.get("dofus_username"),
            "roles": user.get("roles", []),
        },
        "successId": success_id,
        "successName": success_name,
        "successDescription": success_description,
        "description": description,
        "images": image_paths,
        "createdAt": now.isoformat(),
        "status": "pending",
    }

    database = await get_database()
    await database[CLAIM_COLLECTION].insert_one(claim)
    return _serialize(claim)


def validate_image_content_types(content_types: list[str]) -> bool:
    return all(content_type in SUPPORTED_IMAGE_TYPES for content_type in content_types)


def _store_images(claim_id: str, images: list[tuple[str, bytes]]) -> list[str]:
    settings = get_settings()
    upload_dir = Path(settings.claim_upload_dir) / claim_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    image_paths: list[str] = []
    for index, (content_type, image_bytes) in enumerate(images, start=1):
        image_format = SUPPORTED_IMAGE_TYPES[content_type]
        image_path = upload_dir / f"proof_{index}.{image_format}"

        with Image.open(BytesIO(image_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(MAX_IMAGE_SIZE)
            if image_format == "jpg":
                image = image.convert("RGB")
                image.save(image_path, "JPEG", quality=85, optimize=True)
            else:
                image.save(image_path, "PNG", optimize=True)

        image_paths.append(str(image_path))

    return image_paths


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "_id"}
