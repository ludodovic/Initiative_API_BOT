"""Remove local mock users and companion test state before real-user testing."""

import argparse
import asyncio

from app.config import get_settings
from app.db import close_mongo_client, get_database


async def reset_local_companion_data(apply: bool) -> dict[str, int]:
    """Count or delete only disposable local companion data."""
    settings = get_settings()
    if settings.mongodb_database != "initiative_dev":
        raise RuntimeError("This cleanup only runs against the initiative_dev database")
    database = await get_database()
    collections = {
        "mock users": (
            "users",
            {"$or": [{"devFixture": True}, {"discord_id": None}, {"discord_id": {"$exists": False}}]},
        ),
        "companion drafts": ("companion_drafts", {}),
        "companion tournaments": ("companion_tournaments", {}),
    }
    counts: dict[str, int] = {}
    try:
        for label, (collection, query) in collections.items():
            counts[label] = await database[collection].count_documents(query)
            if apply and counts[label]:
                await database[collection].delete_many(query)
    finally:
        await close_mongo_client()
    return counts


def main() -> None:
    """Run dry by default and require --apply for deletion."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Delete the listed local records")
    arguments = parser.parse_args()
    counts = asyncio.run(reset_local_companion_data(arguments.apply))
    action = "Deleted" if arguments.apply else "Found"
    print(", ".join(f"{action} {count} {label}" for label, count in counts.items()))


if __name__ == "__main__":
    main()
