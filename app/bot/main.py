import asyncio
import logging

import discord
from discord.ext import commands

from app.config import get_settings
from app.db import close_mongo_client
from app.services.user_registration_service import (
    build_registration_link,
    create_registered_user,
)

logger = logging.getLogger(__name__)


def build_bot() -> commands.Bot:
    settings = get_settings()
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.reactions = True
    bot = commands.Bot(command_prefix=settings.discord_command_prefix, intents=intents)

    @bot.event
    async def on_ready() -> None:
        logger.info("Discord bot connected as %s", bot.user)

    @bot.command(name="register_message")
    @commands.has_permissions(manage_guild=True)
    async def register_message_command(
        ctx: commands.Context,
        channel: discord.TextChannel,
        *,
        message: str,
    ) -> None:
        emoji = discord.utils.get(ctx.guild.emojis, name=settings.discord_registration_emoji)
        if emoji is None:
            await ctx.send(f"Emoji :{settings.discord_registration_emoji}: not found on this server.")
            return

        registration_message = await channel.send(message)
        await registration_message.add_reaction(emoji)
        await ctx.send(f"Registration message posted in {channel.mention}.")

    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == bot.user.id or payload.guild_id is None:
            return

        if payload.emoji.name != settings.discord_registration_emoji:
            return

        guild = bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        if message.author.id != bot.user.id:
            return

        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.NotFound:
                return

        roles = [role.name for role in member.roles if role.name != "@everyone"]
        dofus_username = member.nick or member.display_name
        user = await create_registered_user(
            discord_username=str(member),
            dofus_username=dofus_username,
            roles=roles,
        )

        registration_link = build_registration_link(user["token"], settings.registration_url)
        try:
            await member.send(registration_link)
        except discord.Forbidden:
            logger.warning("Could not send registration DM to %s", member)

    return bot


async def close_bot_resources() -> None:
    await close_mongo_client()


async def run_bot() -> None:
    settings = get_settings()
    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN is required to run the bot.")

    bot = build_bot()
    try:
        await bot.start(settings.discord_token)
    finally:
        await close_bot_resources()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
