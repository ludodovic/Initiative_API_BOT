import discord
import logging
from typing import Any

from app.db import get_database

logger = logging.getLogger(__name__)

CONFIG_COLLECTION = "bot_config"

# Noms des rôles
RULES_ACCEPTED_ROLE_NAME = "Règlement accepté"
EVENT_ROLE_NAME = "Event"

# Emoji pour les règles
RULES_EMOJI = "\N{WHITE HEAVY CHECK MARK}"


async def set_rules_message(guild_id: int, message_id: int) -> None:
    """Enregistre l'ID du message des règles pour un guild."""
    database = await get_database()
    await database[CONFIG_COLLECTION].update_one(
        {"guild_id": guild_id},
        {"$set": {"rules_message_id": message_id}},
        upsert=True,
    )


async def get_rules_message(guild_id: int) -> int | None:
    """Récupère l'ID du message des règles pour un guild."""
    database = await get_database()
    config = await database[CONFIG_COLLECTION].find_one({"guild_id": guild_id})
    if config is None:
        return None
    
    message_id = config.get("rules_message_id")
    return int(message_id) if message_id else None


async def set_event_message(guild_id: int, message_id: int, reaction_name: str) -> None:
    """Enregistre l'ID du message et la réaction pour l'événement."""
    database = await get_database()
    await database[CONFIG_COLLECTION].update_one(
        {"guild_id": guild_id},
        {
            "$set": {
                "event_message_id": message_id,
                "event_reaction": reaction_name,
            }
        },
        upsert=True,
    )


async def get_event_message(guild_id: int) -> tuple[int | None, str | None]:
    """Récupère l'ID du message et la réaction pour l'événement."""
    database = await get_database()
    config = await database[CONFIG_COLLECTION].find_one({"guild_id": guild_id})
    if config is None:
        return None, None
    
    message_id = config.get("event_message_id")
    reaction = config.get("event_reaction")
    
    return (
        int(message_id) if message_id else None,
        str(reaction) if reaction else None,
    )


async def handle_rules_reaction(
    bot: discord.Client,
    payload: discord.RawReactionActionEvent,
    is_add: bool,
) -> None:
    """
    Gère l'ajout/retrait du rôle "Règlement accepté" quand un utilisateur
    réagit avec :white_check_mark: sur le message des règles.
    
    Args:
        bot: Le client Discord
        payload: L'événement de réaction
        is_add: True si c'est un ajout, False si c'est un retrait
    """
    if payload.guild_id is None:
        return
    
    # Vérifier que c'est la bonne réaction
    if payload.emoji.name != RULES_EMOJI:
        return
    
    # Récupérer le message des règles
    rules_message_id = await get_rules_message(payload.guild_id)
    if rules_message_id is None or rules_message_id != payload.message_id:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    
    # Trouver le rôle "Règlement accepté"
    role = discord.utils.get(guild.roles, name=RULES_ACCEPTED_ROLE_NAME)
    if role is None:
        logger.warning("Role '%s' not found in guild %s", RULES_ACCEPTED_ROLE_NAME, guild.id)
        return
    
    # Récupérer le membre
    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return
    
    if member is None:
        return
    
    # Attribuer ou retirer le rôle
    if is_add:
        await member.add_roles(role)
        logger.info("Added '%s' role to %s", RULES_ACCEPTED_ROLE_NAME, member)
    else:  # Retrait
        await member.remove_roles(role)
        logger.info("Removed '%s' role from %s", RULES_ACCEPTED_ROLE_NAME, member)


async def handle_event_reaction(
    bot: discord.Client,
    payload: discord.RawReactionActionEvent,
    is_add: bool,
) -> None:
    """
    Gère l'ajout/retrait du rôle "Event" quand un utilisateur
    réagit avec la réaction configurée sur le message de l'événement.
    
    Args:
        bot: Le client Discord
        payload: L'événement de réaction
        is_add: True si c'est un ajout, False si c'est un retrait
    """
    if payload.guild_id is None:
        return
    
    # Récupérer le message et la réaction de l'événement
    event_message_id, event_reaction = await get_event_message(payload.guild_id)
    print(f"- Event message ID: {event_message_id}, Event reaction: {event_reaction}")
    
    if event_message_id is None or event_message_id != payload.message_id:
        return
    
    if event_reaction is None or payload.emoji.name != event_reaction:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    
    # Trouver le rôle "Event"
    role = discord.utils.get(guild.roles, name=EVENT_ROLE_NAME)
    if role is None:
        logger.warning("Role '%s' not found in guild %s", EVENT_ROLE_NAME, guild.id)
        return
    
    # Récupérer le membre
    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return
    
    if member is None:
        return
    
    # Attribuer ou retirer le rôle
    if is_add:
        await member.add_roles(role)
        logger.info("Added '%s' role to %s", EVENT_ROLE_NAME, member)
    else:  # Retrait
        await member.remove_roles(role)
        logger.info("Removed '%s' role from %s", EVENT_ROLE_NAME, member)
