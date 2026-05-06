from discord.ext import commands

_bot: commands.Bot | None = None


def set_bot(bot: commands.Bot) -> None:
    global _bot
    _bot = bot


def get_bot() -> commands.Bot | None:
    return _bot
