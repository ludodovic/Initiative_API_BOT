from typing import Any

import discord
from app.config import get_settings
from app.db import get_database

USER_COLLECTION = "users"


async def sync_all_guild_members(bot: discord.Client) -> int:
    """
    Synchronise tous les membres du guild configuré avec la base de données.
    Récupère pour chaque membre: discord_id, discord_username, dofus_username (alias), roles.
    Retourne le nombre de membres synchronisés.
    """
    settings = get_settings()
    
    # Si pas de guild_id configuré, ne pas synchroniser
    if settings.discord_guild_id == 0:
        return 0
    
    guild = bot.get_guild(settings.discord_guild_id)
    
    if guild is None:
        return 0
    
    database = await get_database()
    users_collection = database[USER_COLLECTION]
    
    synced_count = 0
    
    for member in guild.members:
        # Ignorer les bots
        if member.bot:
            continue
        
        # Extraire les informations du membre
        discord_id = member.id
        discord_username = str(member)
        dofus_username = member.nick or member.display_name
        roles = [role.name for role in member.roles if role.name != "@everyone"]
        
        # Mettre à jour ou créer l'utilisateur
        await users_collection.update_one(
            {"discord_id": discord_id},
            {
                "$set": {
                    "discord_id": discord_id,
                    "discord_username": discord_username,
                    "dofus_username": dofus_username,
                    "roles": roles,
                },
                "$setOnInsert": {
                    "achievement": [],
                    "token": None,
                }
            },
            upsert=True,
        )
        synced_count += 1
    
    return synced_count
