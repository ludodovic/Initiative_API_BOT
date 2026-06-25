import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.config import get_settings
from app.db import close_mongo_client
from app.bot.runtime import set_bot
from app.services.success_validation_service import (
    approve_validation,
    create_validation_request,
    find_success,
    get_validation_channel,
    get_validation_request,
    refuse_validation,
    set_validation_channel,
)
from app.services.member_sync_service import sync_all_guild_members
from app.services.user_registration_service import (
    build_registration_link,
    create_registered_user,
)

logger = logging.getLogger(__name__)
APPROVE_EMOJI = "\N{WHITE HEAVY CHECK MARK}"
REFUSE_EMOJI = "\N{CROSS MARK}"
STAFF_ROLE_NAME = "Conseil"


def build_bot() -> commands.Bot:
    settings = get_settings()
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.reactions = True
    bot = commands.Bot(command_prefix=settings.discord_command_prefix, intents=intents)
    set_bot(bot)
    slash_commands_synced = False

    @bot.event
    async def on_ready() -> None:
        nonlocal slash_commands_synced
        logger.info("Discord bot connected as %s", bot.user)
        
        # Synchroniser tous les membres du guild au démarrage
        synced_count = await sync_all_guild_members(bot)
        if synced_count > 0:
            logger.info("Synchronized %d guild members", synced_count)
        
        if not slash_commands_synced:
            if settings.discord_guild_id:
                guild = discord.Object(id=settings.discord_guild_id)
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
            else:
                await bot.tree.sync()
            slash_commands_synced = True

    @bot.event
    async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CheckFailure):
            await ctx.send(f"This command is reserved for the `{STAFF_ROLE_NAME}` role.")
            return
        raise error

    @bot.command(name="register_message")
    @commands.check(_has_staff_role)
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

    @bot.command(name="set_validation_channel")
    @commands.check(_has_staff_role)
    async def set_validation_channel_command(
        ctx: commands.Context,
        channel: discord.TextChannel,
    ) -> None:
        await set_validation_channel(ctx.guild.id, channel.id)
        await ctx.send(f"Success validation entries will be sent to {channel.mention}.")

    @bot.command(name="succes", aliases=["succes_accompli"])
    async def success_command(
        ctx: commands.Context,
        *,
        raw_arguments: str,
    ) -> None:
        if ctx.guild is None:
            await ctx.send("This command can only be used on a server.")
            return

        success_reference, mentioned_members = _parse_prefix_success_arguments(ctx, raw_arguments)
        if not success_reference:
            await ctx.send("Usage: `!succes success name or number @member @member`")
            return

        selected_members = _unique_members([ctx.author, *mentioned_members])
        result = await _create_success_validation_entries(
            guild=ctx.guild,
            requester=ctx.author,
            success_reference=success_reference,
            members=selected_members,
        )
        await ctx.send(result)

    @bot.tree.command(
        name="succes_accompli",
        description="Declare a completed success for yourself and tagged members.",
    )
    @app_commands.describe(
        succes="Success name or success number.",
        membre_1="A member associated with the success.",
        membre_2="A member associated with the success.",
        membre_3="A member associated with the success.",
        membre_4="A member associated with the success.",
        membre_5="A member associated with the success.",
    )
    async def slash_success_command(
        interaction: discord.Interaction,
        succes: str,
        membre_1: discord.Member | None = None,
        membre_2: discord.Member | None = None,
        membre_3: discord.Member | None = None,
        membre_4: discord.Member | None = None,
        membre_5: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command can only be used on a server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        selected_members = _unique_members(
            [
                interaction.user,
                membre_1,
                membre_2,
                membre_3,
                membre_4,
                membre_5,
            ]
        )
        result = await _create_success_validation_entries(
            guild=interaction.guild,
            requester=interaction.user,
            success_reference=succes,
            members=selected_members,
        )
        await interaction.followup.send(result, ephemeral=True)

    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == bot.user.id or payload.guild_id is None:
            return

        if payload.emoji.name in {APPROVE_EMOJI, REFUSE_EMOJI}:
            await _handle_validation_reaction(bot, payload)
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
            discord_id=member.id,
        )

        registration_link = build_registration_link(user["token"], settings.registration_url)
        try:
            await member.send(registration_link)
        except discord.Forbidden:
            logger.warning("Could not send registration DM to %s", member)

    return bot


async def _create_success_validation_entries(
    guild: discord.Guild,
    requester: discord.Member,
    success_reference: str,
    members: list[discord.Member],
) -> str:
    validation_channel_id = await get_validation_channel(guild.id)
    if validation_channel_id is None:
        return "No validation channel configured. Conseil must run `!set_validation_channel #channel` first."

    validation_channel = guild.get_channel(validation_channel_id)
    if not isinstance(validation_channel, discord.TextChannel):
        return "The configured validation channel was not found. Staff must configure it again."

    success = await find_success(success_reference)
    if success is None:
        return f"Success `{success_reference}` was not found."

    success_id = int(success["id"])
    success_name = str(success["name"])

    for member in members:
        message = await validation_channel.send(
            "**Success waiting for validation**\n"
            f"Success: **{success_name}** (`{success_id}`)\n"
            f"Completed by: {member.mention} (`{member.display_name}`)\n"
            f"Declared by: {requester.mention}\n"
            f"Status: pending"
        )
        await create_validation_request(
            guild_id=guild.id,
            channel_id=validation_channel.id,
            message_id=message.id,
            requester_discord_username=str(requester),
            member_discord_username=str(member),
            member_display_name=member.display_name,
            success_id=success_id,
            success_name=success_name,
        )
        await message.add_reaction(APPROVE_EMOJI)
        await message.add_reaction(REFUSE_EMOJI)

    return f"{len(members)} validation entr{'y' if len(members) == 1 else 'ies'} sent to {validation_channel.mention}."


async def _handle_validation_reaction(
    bot: commands.Bot,
    payload: discord.RawReactionActionEvent,
) -> None:
    validation = await get_validation_request(payload.message_id)
    if validation is None or validation.get("status") != "pending":
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    staff_member = guild.get_member(payload.user_id)
    if staff_member is None:
        try:
            staff_member = await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return

    if not _member_has_staff_role(staff_member):
        return

    channel = bot.get_channel(payload.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    if payload.emoji.name == APPROVE_EMOJI:
        updated_validation = await approve_validation(payload.message_id)
        status = "approved"
    else:
        updated_validation = await refuse_validation(payload.message_id)
        status = "refused"

    if updated_validation is None:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    await message.edit(
        content=(
            "**Success validation completed**\n"
            f"Success: **{updated_validation['success_name']}** (`{updated_validation['success_id']}`)\n"
            f"Completed by: `{updated_validation['member_display_name']}`\n"
            f"Validated by: {staff_member.mention}\n"
            f"Status: {status}"
        )
    )
    try:
        await message.clear_reactions()
    except discord.Forbidden:
        logger.warning("Could not clear reactions from validation message %s", message.id)


def _unique_members(members: list[discord.Member | None]) -> list[discord.Member]:
    unique_members: list[discord.Member] = []
    seen_member_ids: set[int] = set()

    for member in members:
        if member is None or member.id in seen_member_ids:
            continue
        unique_members.append(member)
        seen_member_ids.add(member.id)

    return unique_members


def _has_staff_role(ctx: commands.Context) -> bool:
    return isinstance(ctx.author, discord.Member) and _member_has_staff_role(ctx.author)


def _member_has_staff_role(member: discord.Member) -> bool:
    return any(role.name == STAFF_ROLE_NAME for role in member.roles)


def _parse_prefix_success_arguments(
    ctx: commands.Context,
    raw_arguments: str,
) -> tuple[str, list[discord.Member]]:
    success_reference = raw_arguments
    for member in ctx.message.mentions:
        success_reference = success_reference.replace(f"<@{member.id}>", "")
        success_reference = success_reference.replace(f"<@!{member.id}>", "")

    return success_reference.strip(), [
        member for member in ctx.message.mentions if isinstance(member, discord.Member)
    ]


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
