import asyncio
import logging

import uvicorn

from app.api.main import app
from app.bot.main import build_bot
from app.config import get_settings


async def run_api() -> None:
    settings = get_settings()
    config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot() -> None:
    settings = get_settings()
    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN is required to run the bot.")

    bot = build_bot()
    await bot.start(settings.discord_token)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await asyncio.gather(run_api(), run_bot())


if __name__ == "__main__":
    asyncio.run(main())
