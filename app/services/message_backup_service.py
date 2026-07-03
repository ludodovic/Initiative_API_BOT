import discord
import logging
from typing import Any

from app.config import get_settings
from app.db import get_database

logger = logging.getLogger(__name__)

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


async def restore_forum_data(bot: discord.Client) -> int:
    """
    Restaure les forums à partir de la collection sauvegarde forum.
    Pour chaque forum sauvegardé, trouve le channel forum avec le même nom
    et recrée les posts avec leurs messages et images.
    Retourne le nombre de forums restaurés.
    """
    settings = get_settings()
    guild = bot.get_guild(settings.discord_guild_id)
    
    if guild is None:
        return 0
    
    database = await get_database()
    forum_collection = database[FORUM_COLLECTION]
    
    restored_count = 0
    
    # Récupérer tous les forums sauvegardés
    saved_forums = await forum_collection.find({}).to_list(length=None)
    
    for saved_forum in saved_forums:
        forum_name = saved_forum.get("forum_name")
        if not forum_name:
            continue
        
        # Trouver le channel forum avec ce nom
        forum_channel = discord.utils.get(guild.forums, name=forum_name)
        if forum_channel is None or not isinstance(forum_channel, discord.ForumChannel):
            continue
        
        posts = saved_forum.get("posts", [])
        if not posts:
            continue
        
        # Restaurer chaque post comme un thread
        for post in posts:
            post_title = post.get("post_title", "Sans titre")
            messages = post.get("messages", [])
            
            if not messages:
                continue
            
            # Créer le thread avec le premier message
            first_message = messages[0]
            first_content = first_message.get("content", "")
            first_images = first_message.get("images", [])
            
            # Ajouter les images du premier message au contenu
            content_with_images = first_content
            if first_images:
                content_with_images += "\n" + "\n".join(first_images)
            
            try:
                # Créer le thread
                thread = await forum_channel.create_thread(
                    name=post_title,
                    content=content_with_images[:2000]  # Limite de 2000 caractères
                )
                
                # Envoyer les autres messages dans le thread
                for msg in messages[1:]:
                    msg_content = msg.get("content", "")
                    msg_images = msg.get("images", [])
                    
                    text_content = msg_content
                    if msg_images:
                        text_content += "\n" + "\n".join(msg_images)
                    
                    if text_content:
                        await thread.send(content=text_content[:2000])
                
                restored_count += 1
            except Exception as e:
                logger.error(f"Error restoring post {post_title}: {e}")
                continue
    
    return restored_count


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
        
        # Récupérer tous les threads (posts) du forum
        try:
            threads = forum.threads
        except Exception:
            continue
        
        posts = []
        
        for thread in threads:
            # Récupérer tous les messages du thread
            thread_messages = []
            message_id_counter = 1
            
            try:
                async for message in thread.history(oldest_first=True):
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
