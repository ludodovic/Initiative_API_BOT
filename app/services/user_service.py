from typing import Any

from app.db import get_database


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
