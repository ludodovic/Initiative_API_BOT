"""Service for handling member leave notifications."""

from datetime import datetime
from typing import Any

import discord
from app.db import get_database
from app.config import get_settings

CONFIG_COLLECTION = "bot_config"
USER_COLLECTION = "users"


async def set_leave_notification_channel(guild_id: int, channel_id: int) -> None:
    """Set the leave notification channel for a guild."""
    database = await get_database()
    await database[CONFIG_COLLECTION].update_one(
        {"guild_id": guild_id},
        {"$set": {"leave_notification_channel_id": channel_id}},
        upsert=True,
    )


async def get_leave_notification_channel(guild_id: int) -> int | None:
    """Get the leave notification channel ID for a guild."""
    database = await get_database()
    config = await database[CONFIG_COLLECTION].find_one({"guild_id": guild_id})
    if config is None:
        return None

    channel_id = config.get("leave_notification_channel_id")
    return int(channel_id) if channel_id else None


async def handle_member_leave(member: discord.Member) -> None:
    """
    Handle a member leaving the guild.
    - Find the user in the database by discord_id
    - Clear their roles list
    - Add left_server date
    - Send notification to configured channel
    """
    settings = get_settings()
    
    # Only handle members from the configured guild
    if member.guild.id != settings.discord_guild_id:
        return
    
    # Get the leave notification channel
    channel_id = await get_leave_notification_channel(member.guild.id)
    if channel_id is None:
        # Also check if channel is set in settings (for backwards compatibility)
        if settings.discord_leave_notification_channel_id == 0:
            return
        channel_id = settings.discord_leave_notification_channel_id
    
    channel = member.guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    
    # Find the user in the database
    database = await get_database()
    user = await database[USER_COLLECTION].find_one({"discord_id": member.id})
    
    if user is None:
        # Try to find by discord_username
        user = await database[USER_COLLECTION].find_one({"discord_username": str(member)})
    
    if user is None:
        # User not found in database, send notification with discord username
        dofus_username = member.nick or member.display_name or str(member)
        await _send_leave_notification(channel, dofus_username)
        return
    
    # Update the user in the database
    dofus_username = user.get("dofus_username", str(member))
    
    # Clear roles and add left_server date
    await database[USER_COLLECTION].update_one(
        {"discord_id": member.id},
        {
            "$set": {
                "roles": [],
                "left_server": datetime.utcnow().isoformat(),
            }
        },
    )
    
    # Send notification
    await _send_leave_notification(channel, dofus_username)


async def _send_leave_notification(channel: discord.TextChannel, dofus_username: str) -> None:
    """Send an embed notification to the channel."""
    now = datetime.now()
    
    # Format the date in French
    # Mapping for French month names
    french_months = {
        1: "janvier", 2: "février", 3: "mars", 4: "avril",
        5: "mai", 6: "juin", 7: "juillet", 8: "août",
        9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"
    }
    
    formatted_date = f"{now.day} {french_months[now.month]} {now.year} à {now.hour}:{now.minute:02d}:{now.second:02d}"
    
    # Create the embed
    embed = discord.Embed(
        title="Membre parti",
        description=f"Le membre **{dofus_username}** a quitté le serveur à **{formatted_date}**",
        color=discord.Color.red(),
    )
    
    await channel.send(embed=embed)
