from pathlib import Path

import discord
from discord.ext import commands

from app.config import get_settings
from app.services.success_validation_service import (
    create_validation_request,
    get_validation_channel,
)

APPROVE_EMOJI = "\N{WHITE HEAVY CHECK MARK}"
REFUSE_EMOJI = "\N{CROSS MARK}"


async def post_success_claim_for_validation(
    bot: commands.Bot,
    claim: dict,
) -> None:
    settings = get_settings()
    if not settings.discord_guild_id:
        raise RuntimeError("DISCORD_GUILD_ID is required to post API claims to Discord.")

    guild = bot.get_guild(settings.discord_guild_id)
    if guild is None:
        raise RuntimeError("Configured Discord guild was not found.")

    validation_channel_id = await get_validation_channel(guild.id)
    if validation_channel_id is None:
        raise RuntimeError("No validation channel configured.")

    channel = guild.get_channel(validation_channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("Configured validation channel was not found.")

    user = claim["user"]
    image_paths = claim.get("images", [])
    files = [discord.File(path, filename=Path(path).name) for path in image_paths]
    message = await channel.send(
        "**Success waiting for validation**\n"
        f"Success: **{claim['successName']}** (`{claim['successId']}`)\n"
        f"Description: {claim['successDescription']}\n"
        f"Completed by: `{user.get('dofus_username') or user.get('discord_username')}`\n"
        f"Declared from website by: `{user.get('discord_username')}`\n"
        f"Claim: `{claim['claimId']}`\n"
        f"User note: {claim['description'] or 'None'}\n"
        f"Status: pending",
        files=files,
    )

    await create_validation_request(
        guild_id=guild.id,
        channel_id=channel.id,
        message_id=message.id,
        requester_discord_username=str(user.get("discord_username")),
        member_discord_username=str(user.get("discord_username")),
        member_display_name=str(user.get("dofus_username") or user.get("discord_username")),
        success_id=int(claim["successId"]),
        success_name=str(claim["successName"]),
        claim_id=str(claim["claimId"]),
        proof_image_paths=image_paths,
    )
    await message.add_reaction(APPROVE_EMOJI)
    await message.add_reaction(REFUSE_EMOJI)
