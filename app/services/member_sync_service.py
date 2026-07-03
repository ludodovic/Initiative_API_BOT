import discord
from datetime import datetime
from app.config import get_settings
from app.db import get_database

BACKUP_COLLECTION = "Sauvegarde discord"
MISC_COLLECTION = "misc"

# Rôles à restaurer lors de l'arrivée d'un membre
RESTORABLE_ROLES = ["Assemblée", "Initiateur", "Ancien membre"]


async def restore_member_roles(member: discord.Member) -> int:
    """
    Attribue les rôles sauvegardés à un membre qui rejoint le serveur.
    Cherche dans la collection Sauvegarde discord par discord_id ou discord_username.
    N'attribue que les rôles dans RESTORABLE_ROLES.
    Retourne le nombre de rôles attribués.
    """
    database = await get_database()
    backup_collection = database[BACKUP_COLLECTION]
    
    # Chercher le membre dans la sauvegarde
    user_data = await backup_collection.find_one(
        {"$or": [
            {"discord_id": member.id},
            {"discord_username": str(member)}
        ]}
    )
    
    if user_data is None:
        return 0
    
    # Récupérer les rôles sauvegardés
    saved_roles = user_data.get("roles", [])
    if not saved_roles:
        return 0
    
    # Filtrer les rôles à restaurer
    roles_to_restore = [role for role in saved_roles if role in RESTORABLE_ROLES]
    if not roles_to_restore:
        return 0
    
    # Trouver les rôles correspondants dans le guild
    guild = member.guild
    roles_to_add = []
    for role_name in roles_to_restore:
        role = discord.utils.get(guild.roles, name=role_name)
        if role is not None:
            roles_to_add.append(role)
    
    if not roles_to_add:
        return 0
    
    # Attribuer les rôles
    try:
        await member.add_roles(*roles_to_add)
        return len(roles_to_add)
    except Exception:
        return 0


async def save_server_owner(bot: discord.Client) -> bool:
    """
    Sauvegarde les informations du propriétaire du serveur dans la collection misc.
    Retourne True si la sauvegarde a réussi, False sinon.
    """
    settings = get_settings()
    guild = bot.get_guild(settings.discord_guild_id)
    
    if guild is None or guild.owner is None:
        return False
    
    database = await get_database()
    misc_collection = database[MISC_COLLECTION]
    
    # Stocker les informations du propriétaire
    await misc_collection.update_one(
        {"type": "server_owner"},
        {
            "$set": {
                "owner_name": str(guild.owner),
                "owner_id": guild.owner.id,
                "date": datetime.utcnow().isoformat(),
            }
        },
        upsert=True,
    )
    
    return True


async def sync_all_guild_members(bot: discord.Client) -> int:
    """
    Synchronise tous les membres du guild configuré avec la collection Sauvegarde discord.
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
    backup_collection = database[BACKUP_COLLECTION]
    
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
        
        # Mettre à jour ou créer le membre dans la sauvegarde
        await backup_collection.update_one(
            {"discord_id": discord_id},
            {
                "$set": {
                    "discord_id": discord_id,
                    "discord_username": discord_username,
                    "dofus_username": dofus_username,
                    "roles": roles,
                }
            },
            upsert=True,
        )
        synced_count += 1
    
    return synced_count
