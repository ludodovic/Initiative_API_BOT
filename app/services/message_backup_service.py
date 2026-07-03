import discord
from typing import Any

from app.config import get_settings
from app.db import get_database

FORUM_COLLECTION = "sauvegarde forum"
MESSAGE_COLLECTION = "sauvegarde message"

# IDs des forums à sauvegarder
FORUM_CHANNEL_IDS = [1475808996043522140, 1438842398787764255]


async def backup_all_messages(bot: discord.Client) -> tuple[int, int]:
    """
    Sauvegarde tous les messages des forums et channels textuels.
    Retourne (nombre_de_forums, nombre_de_messages_textuels).
    """
    forums_backed_up = await _backup_forum_channels(bot)
    messages_backed_up = 1 # await _backup_text_channels(bot)
    return forums_backed_up, messages_backed_up


async def _backup_forum_channels(bot: discord.Client) -> int:
    """
    Sauvegarde les messages des forums spécifiés.
    Retourne le nombre de forums sauvegardés.
    """
    settings = get_settings()
    guild = bot.get_guild(settings.discord_guild_id)
    
    if guild is None:
        return 0
    
    database = await get_database()
    forum_collection = database[FORUM_COLLECTION]
    
    backed_up_count = 0
    
    for forum_id in FORUM_CHANNEL_IDS:
        forum = guild.get_channel(forum_id)
        
        # Vérifier que le channel existe et est un forum
        if forum is None or not isinstance(forum, discord.ForumChannel):
            continue
        
        # Récupérer tous les threads (posts) du forum - actifs ET archivés
        # Threads actifs
        active_threads = []
        try:
            active_threads = forum.threads
        except Exception:
            pass
        
        # Threads archivés
        try:
            async for archived_thread in forum.fetch_archived_threads(limit=None):
                active_threads.append(archived_thread.copy())
        except Exception:
            pass
        
        threads = active_threads
        
        posts = []
        
        for thread in threads:
            # Récupérer tous les messages du thread
            thread_messages = []
            message_id_counter = 1
            
            try:
                async for message in thread.history(limit=None, oldest_first=True):
                    # Ignorer les messages des bots
                    if message.author.bot:
                        continue
                    
                    # Récupérer les images (attachments)
                    images = [attachment.url for attachment in message.attachments]
                    
                    thread_messages.append({
                        "author": str(message.author),
                        "content": message.content,
                        "message_id": message_id_counter,
                        "images": images,
                    })
                    message_id_counter += 1
            except Exception:
                pass
            
            if thread_messages:
                posts.append({
                    "post_title": thread.name,
                    "date": thread.created_at.isoformat() if thread.created_at else None,
                    "messages": thread_messages,
                })
        
        if posts:
            # Supprimer l'ancien document du forum s'il existe
            await forum_collection.delete_many({"forum_name": forum.name})
            
            # Insérer le nouveau
            await forum_collection.insert_one({
                "forum_name": forum.name,
                "posts": posts,
            })
            backed_up_count += 1
    
    return backed_up_count


async def _backup_text_channels(bot: discord.Client) -> int:
    """
    Sauvegarde les 200 derniers messages de tous les channels textuels.
    Retourne le nombre total de messages sauvegardés.
    """
    settings = get_settings()
    guild = bot.get_guild(settings.discord_guild_id)
    
    if guild is None:
        return 0
    
    database = await get_database()
    message_collection = database[MESSAGE_COLLECTION]
    
    total_backed_up = 0
    
    # Pré-récupérer le dernier ID pour chaque channel
    channel_last_ids = {}
    for channel in guild.text_channels:
        if not isinstance(channel, discord.TextChannel):
            continue
        
        last_message = await message_collection.find_one(
            {"channel_name": channel.name},
            sort=[("id", -1)]
        )
        channel_last_ids[channel.name] = last_message["id"] + 1 if last_message else 1
    
    # Récupérer tous les channels textuels
    for channel in guild.text_channels:
        # Ignorer les channels de type news et autres
        if not isinstance(channel, discord.TextChannel):
            continue
        
        # Récupérer le compteur pour ce channel
        next_id = channel_last_ids.get(channel.name, 1)
        
        # Récupérer les 200 derniers messages
        try:
            messages = []
            async for message in channel.history(limit=500, oldest_first=True):
                # Ignorer les messages des bots
                if message.author.bot:
                    continue
                
                # Récupérer les images (attachments)
                images = [attachment.url for attachment in message.attachments]
                
                messages.append({
                    "channel_name": channel.name,
                    "author": str(message.author),
                    "content": message.content,
                    "id": next_id,
                    "images": images,
                })
                next_id += 1
            
            # Insérer tous les messages
            if messages:
                await message_collection.insert_many(messages)
                total_backed_up += len(messages)
        except Exception:
            pass
    
    return total_backed_up
