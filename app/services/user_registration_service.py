import secrets
from typing import Any

from app.db import get_database


USER_COLLECTION = "users"


async def create_registered_user(
    discord_username: str,
    dofus_username: str,
    roles: list[str],
) -> dict[str, Any]:
    database = await get_database()
    users = database[USER_COLLECTION]

    existing_user = await users.find_one({"discord_username": discord_username})
    if existing_user is not None:
        return _serialize_user(existing_user)

    last_user = await users.find_one(sort=[("id", -1)])
    next_id = int(last_user["id"]) + 1 if last_user and "id" in last_user else 1

    user = {
        "id": next_id,
        "discord_username": discord_username,
        "dofus_username": dofus_username,
        "roles": roles,
        "achievement": [],
        "token": secrets.token_urlsafe(32),
    }

    await users.insert_one(user)
    return _serialize_user(user)


def build_registration_link(token: str, base_url: str) -> str:
    return f"{base_url.rstrip('/')}?token={token}"


def _serialize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in user.items() if key != "_id"}
