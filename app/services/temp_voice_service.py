import asyncio
import discord
import logging
from typing import Any

from app.db import get_database

logger = logging.getLogger(__name__)

CONFIG_COLLECTION = "bot_config"

# Préfixe pour les salons temporaires
TEMP_VOICE_PREFIX = "Salon de "


async def set_temp_voice_channel(guild_id: int, channel_id: int) -> None:
    """Enregistre le channel vocal qui déclenche la création de salons temporaires."""
    database = await get_database()
    await database[CONFIG_COLLECTION].update_one(
        {"guild_id": guild_id},
        {"$set": {"temp_voice_channel_id": channel_id}},
        upsert=True,
    )


async def get_temp_voice_channel(guild_id: int) -> int | None:
    """Récupère l'ID du channel vocal qui déclenche la création."""
    database = await get_database()
    config = await database[CONFIG_COLLECTION].find_one({"guild_id": guild_id})
    if config is None:
        return None
    
    channel_id = config.get("temp_voice_channel_id")
    return int(channel_id) if channel_id else None


async def handle_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    """
    Gère la création et suppression des salons vocaux temporaires.
    
    - Quand un membre rejoint le channel configuré : crée un salon temporaire
    - Quand un membre quitte un salon temporaire : supprime si vide
    """
    # Ignorer les bots
    if member.bot:
        return
    
    guild = member.guild
    
    # Récupérer le channel configuré
    temp_voice_channel_id = await get_temp_voice_channel(guild.id)
    if temp_voice_channel_id is None:
        return
    
    # Vérifier si le membre rejoint le channel configuré
    if after.channel and after.channel.id == temp_voice_channel_id:
        await _create_temp_voice_channel(member, after.channel)
    
    # Vérifier si le membre quitte un salon temporaire
    if before.channel and _is_temp_voice_channel(before.channel):
        await _check_and_delete_empty_channel(before.channel)


async def _create_temp_voice_channel(member: discord.Member, parent_channel: discord.VoiceChannel) -> None:
    """
    Crée un salon vocal temporaire pour le membre.
    - Nom : "Salon de [pseudonyme du serveur]"
    - Dans la même catégorie que le channel parent
    - Donne la propriété au membre
    - Déplace le membre dans le nouveau salon
    """
    guild = member.guild
    
    # Obtenir le pseudonyme du serveur (nick) ou le nom d'affichage
    display_name = member.nick or member.display_name
    channel_name = f"{TEMP_VOICE_PREFIX}{display_name}"
    
    try:
        # Créer le channel vocal dans la même catégorie
        category = parent_channel.category
        temp_channel = await guild.create_voice_channel(
            name=channel_name,
            category=category,
            reason=f"Création de salon temporaire pour {member}",
        )
        
        # Donner les permissions au membre (propriétaire)
        await temp_channel.set_permissions(
            member,
            manage_channels=True,
            manage_roles=True,
            mute_members=True,
            deafen_members=True,
            move_members=True,
            connect=True,
            speak=True,
            reason=f"Donner la propriété à {member}",
        )
        
        # Déplacer le membre dans le nouveau salon
        await member.move_to(temp_channel)
        
        logger.info("Created temporary voice channel %s for %s", temp_channel.name, member)
        
    except Exception as e:
        logger.error("Error creating temporary voice channel: %s", e)


async def _check_and_delete_empty_channel(channel: discord.VoiceChannel) -> None:
    """
    Vérifie si un channel vocal est vide et le supprime si c'est le cas.
    """
    # Attendre un court instant pour éviter les faux positifs
    # (le membre peut être en train de changer de salon)
    await asyncio.sleep(1)
    
    # Vérifier si le channel est toujours vide
    if channel.members:
        return
    
    # Vérifier que c'est bien un salon temporaire
    if not _is_temp_voice_channel(channel):
        return
    
    try:
        await channel.delete(reason="Salon vocal temporaire vide")
        logger.info("Deleted empty temporary voice channel %s", channel.name)
    except Exception as e:
        logger.error("Error deleting temporary voice channel %s: %s", channel.name, e)


def _is_temp_voice_channel(channel: discord.VoiceChannel) -> bool:
    """
    Vérifie si un channel vocal est un salon temporaire.
    """
    return channel.name.startswith(TEMP_VOICE_PREFIX)
