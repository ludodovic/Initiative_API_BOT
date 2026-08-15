"""Synchronize real Discord guild members into the configured MongoDB database."""

import asyncio

import discord

from app.config import get_settings
from app.db import close_mongo_client
from app.services.user_registration_service import sync_all_members_to_bdd


async def sync_discord_users() -> None:
    """Connect once, synchronize members, and close the Discord client."""
    settings = get_settings()
    if not settings.discord_token or settings.discord_guild_id == 0:
        raise RuntimeError("DISCORD_TOKEN and DISCORD_GUILD_ID must be configured")
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        result = await sync_all_members_to_bdd(client)
        print(f"Synced Discord users: {result}")
        await client.close()

    try:
        await client.start(settings.discord_token)
    finally:
        await close_mongo_client()


if __name__ == "__main__":
    asyncio.run(sync_discord_users())
