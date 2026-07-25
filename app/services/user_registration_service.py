import secrets
from datetime import datetime
from typing import Any

import discord
from app.db import get_database
from app.config import get_settings


USER_COLLECTION = "users"


async def create_registered_user(
    discord_username: str,
    dofus_username: str,
    roles: list[str],
    discord_id: int | None = None,
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
        "discord_id": discord_id,
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


async def create_or_update_user_from_member(member: discord.Member) -> dict[str, Any] | None:
    """
    Create or update a user in the database from a Discord member.
    Includes all available information: discord_id, discord_username, dofus_username, roles, joined_server.
    Returns the user document or None if creation failed.
    """
    database = await get_database()
    users = database[USER_COLLECTION]
    
    discord_username = str(member)
    dofus_username = member.nick or member.display_name or str(member)
    roles = [role.name for role in member.roles if role.name != "@everyone"]
    
    # Get the join date
    joined_at = member.joined_at
    joined_server_date = joined_at.isoformat() if joined_at else datetime.utcnow().isoformat()
    
    # Check if user exists by discord_id first
    existing_user = await users.find_one({"discord_id": member.id})
    
    if existing_user is not None:
        # Update existing user
        await users.update_one(
            {"discord_id": member.id},
            {
                "$set": {
                    "discord_username": discord_username,
                    "dofus_username": dofus_username,
                    "roles": roles,
                    "joined_server": joined_server_date,
                }
            }
        )
        updated_user = await users.find_one({"discord_id": member.id})
        return _serialize_user(updated_user) if updated_user else None
    
    # Check if user exists by discord_username
    existing_user = await users.find_one({"discord_username": discord_username})
    
    if existing_user is not None:
        # Update existing user with discord_id
        await users.update_one(
            {"discord_username": discord_username},
            {
                "$set": {
                    "discord_id": member.id,
                    "dofus_username": dofus_username,
                    "roles": roles,
                    "joined_server": joined_server_date,
                }
            }
        )
        updated_user = await users.find_one({"discord_username": discord_username})
        return _serialize_user(updated_user) if updated_user else None
    
    # Create new user
    last_user = await users.find_one(sort=[("id", -1)])
    next_id = int(last_user["id"]) + 1 if last_user and "id" in last_user else 1
    
    user = {
        "id": next_id,
        "discord_id": member.id,
        "discord_username": discord_username,
        "dofus_username": dofus_username,
        "roles": roles,
        "achievement": [],
        "joined_server": joined_server_date,
        "token": secrets.token_urlsafe(32),
    }
    
    await users.insert_one(user)
    return _serialize_user(user)


async def sync_all_members_to_bdd(bot: discord.Client) -> dict[str, int]:
    """
    Scan the configured guild and sync all members to the users collection.
    Creates users for members not in the database and updates existing ones.
    Returns a dict with counts: created, updated, skipped.
    """
    settings = get_settings()
    
    if settings.discord_guild_id == 0:
        return {"created": 0, "updated": 0, "skipped": 0}
    
    guild = bot.get_guild(settings.discord_guild_id)
    
    if guild is None:
        return {"created": 0, "updated": 0, "skipped": 0}
    
    database = await get_database()
    users = database[USER_COLLECTION]
    
    created = 0
    updated = 0
    skipped = 0
    
    for member in guild.members:
        # Skip bots
        if member.bot:
            skipped += 1
            continue
        
        discord_username = str(member)
        dofus_username = member.nick or member.display_name or str(member)
        roles = [role.name for role in member.roles if role.name != "@everyone"]
        joined_at = member.joined_at
        joined_server_date = joined_at.isoformat() if joined_at else datetime.utcnow().isoformat()
        
        # Check if user exists
        existing_user = await users.find_one({"discord_id": member.id})
        
        if existing_user is not None:
            # Update existing user
            await users.update_one(
                {"discord_id": member.id},
                {
                    "$set": {
                        "discord_username": discord_username,
                        "dofus_username": dofus_username,
                        "roles": roles,
                        "joined_server": joined_server_date,
                    }
                }
            )
            updated += 1
            continue
        
        # Check by discord_username
        existing_user = await users.find_one({"discord_username": discord_username})
        
        if existing_user is not None:
            # Update with discord_id
            await users.update_one(
                {"discord_username": discord_username},
                {
                    "$set": {
                        "discord_id": member.id,
                        "dofus_username": dofus_username,
                        "roles": roles,
                        "joined_server": joined_server_date,
                    }
                }
            )
            updated += 1
            continue
        
        # Create new user
        last_user = await users.find_one(sort=[("id", -1)])
        next_id = int(last_user["id"]) + 1 if last_user and "id" in last_user else 1
        
        user = {
            "id": next_id,
            "discord_id": member.id,
            "discord_username": discord_username,
            "dofus_username": dofus_username,
            "roles": roles,
            "achievement": [],
            "joined_server": joined_server_date,
            "token": secrets.token_urlsafe(32),
        }
        
        await users.insert_one(user)
        created += 1
    
    return {"created": created, "updated": updated, "skipped": skipped}
