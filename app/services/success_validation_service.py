from difflib import SequenceMatcher
from typing import Any

from app.db import get_database

CONFIG_COLLECTION = "bot_config"
SUCCESS_COLLECTION = "succes"
VALIDATION_COLLECTION = "success_validations"
USER_COLLECTION = "users"


async def set_validation_channel(guild_id: int, channel_id: int) -> None:
    database = await get_database()
    await database[CONFIG_COLLECTION].update_one(
        {"guild_id": guild_id},
        {"$set": {"validation_channel_id": channel_id}},
        upsert=True,
    )


async def get_validation_channel(guild_id: int) -> int | None:
    database = await get_database()
    config = await database[CONFIG_COLLECTION].find_one({"guild_id": guild_id})
    if config is None:
        return None

    channel_id = config.get("validation_channel_id")
    return int(channel_id) if channel_id else None


async def find_success(success_reference: str) -> dict[str, Any] | None:
    database = await get_database()

    if success_reference.isdigit():
        success = await database[SUCCESS_COLLECTION].find_one({"id": int(success_reference)})
        return _serialize(success) if success else None

    normalized_reference = _normalize_success_name(success_reference)
    cursor = database[SUCCESS_COLLECTION].find({})
    best_success: dict[str, Any] | None = None
    best_score = 0.0

    async for success in cursor:
        success_name = success.get("name")
        if not isinstance(success_name, str):
            continue

        normalized_name = _normalize_success_name(success_name)
        if normalized_name == normalized_reference:
            return _serialize(success)

        score = SequenceMatcher(None, normalized_reference, normalized_name).ratio()
        if normalized_reference in normalized_name or normalized_name in normalized_reference:
            score += 0.15

        if score > best_score:
            best_score = score
            best_success = success

    if best_success is None or best_score < 0.6:
        return None

    return _serialize(best_success)


async def create_validation_request(
    guild_id: int,
    channel_id: int,
    message_id: int,
    requester_discord_username: str,
    member_discord_username: str,
    member_display_name: str,
    success_id: int,
    success_name: str,
) -> None:
    database = await get_database()
    await database[VALIDATION_COLLECTION].insert_one(
        {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_id": message_id,
            "requester_discord_username": requester_discord_username,
            "member_discord_username": member_discord_username,
            "member_display_name": member_display_name,
            "success_id": success_id,
            "success_name": success_name,
            "status": "pending",
        }
    )


async def get_validation_request(message_id: int) -> dict[str, Any] | None:
    database = await get_database()
    validation = await database[VALIDATION_COLLECTION].find_one({"message_id": message_id})
    return _serialize(validation) if validation else None


async def approve_validation(message_id: int) -> dict[str, Any] | None:
    database = await get_database()
    validation = await database[VALIDATION_COLLECTION].find_one({"message_id": message_id})
    if validation is None or validation.get("status") != "pending":
        return _serialize(validation) if validation else None

    await database[USER_COLLECTION].update_one(
        {"discord_username": validation["member_discord_username"]},
        {"$addToSet": {"achievement": validation["success_id"]}},
    )
    await database[VALIDATION_COLLECTION].update_one(
        {"message_id": message_id},
        {"$set": {"status": "approved"}},
    )
    validation["status"] = "approved"
    return _serialize(validation)


async def refuse_validation(message_id: int) -> dict[str, Any] | None:
    database = await get_database()
    validation = await database[VALIDATION_COLLECTION].find_one_and_update(
        {"message_id": message_id, "status": "pending"},
        {"$set": {"status": "refused"}},
    )
    if validation is None:
        validation = await database[VALIDATION_COLLECTION].find_one({"message_id": message_id})
    if validation:
        validation["status"] = "refused"
    return _serialize(validation) if validation else None


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "_id"}


def _normalize_success_name(value: str) -> str:
    return " ".join(value.casefold().strip().split())
