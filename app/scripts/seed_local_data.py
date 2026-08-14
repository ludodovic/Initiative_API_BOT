"""Seed eight isolated local users for companion tournament testing."""

import asyncio
from app.db import close_mongo_client, get_database


FIXTURE_USERS: tuple[dict[str, object], ...] = (
    {"id": 1001, "discord_id": 900000000001, "discord_username": "Coccinelle", "dofus_username": "Coccinelle", "roles": ["Conseiller"], "achievement": [], "class": "Cra", "token": "development-only-coccinelle-token", "devFixture": True},
    {"id": 1002, "discord_id": 900000000002, "discord_username": "Ludzu", "dofus_username": "Ludzu", "roles": ["Conseiller"], "achievement": [], "class": "Iop", "token": "development-only-ludzu-token", "devFixture": True},
    {"id": 1003, "discord_id": 900000000003, "discord_username": "Mynni", "dofus_username": "Mynni", "roles": [], "achievement": [], "class": "Eniripsa", "token": "development-only-mynni-token", "devFixture": True},
    {"id": 1004, "discord_id": 900000000004, "discord_username": "Scorpia", "dofus_username": "Scorpia", "roles": [], "achievement": [], "class": "Feca", "token": "development-only-scorpia-token", "devFixture": True},
    {"id": 1005, "discord_id": 900000000005, "discord_username": "Aurore", "dofus_username": "Aurore", "roles": [], "achievement": [], "class": "Sacrieur", "token": "development-only-aurore-token", "devFixture": True},
    {"id": 1006, "discord_id": 900000000006, "discord_username": "Boreal", "dofus_username": "Boreal", "roles": [], "achievement": [], "class": "Xelor", "token": "development-only-boreal-token", "devFixture": True},
    {"id": 1007, "discord_id": 900000000007, "discord_username": "Cendre", "dofus_username": "Cendre", "roles": [], "achievement": [], "class": "Pandawa", "token": "development-only-cendre-token", "devFixture": True},
    {"id": 1008, "discord_id": 900000000008, "discord_username": "Dune", "dofus_username": "Dune", "roles": [], "achievement": [], "class": "Sram", "token": "development-only-dune-token", "devFixture": True},
)


async def seed_local_data() -> None:
    """Upsert the isolated local roster without touching real user IDs."""
    database = await get_database()
    users = database["users"]
    try:
        for user in FIXTURE_USERS:
            await users.update_one({"id": user["id"]}, {"$set": user}, upsert=True)
    finally:
        await close_mongo_client()


if __name__ == "__main__":
    asyncio.run(seed_local_data())
