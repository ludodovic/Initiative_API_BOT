from typing import Any

from app.db import get_database

EMPTY_PROGRESS = {"unlockedList": [], "totalPoints": 0}


async def get_unlocked_successes(token: str | None) -> dict[str, Any]:
    if not token:
        return EMPTY_PROGRESS

    database = await get_database()
    user = await database["users"].find_one({"token": token})
    if user is None:
        return EMPTY_PROGRESS

    achievement_ids = user.get("achievement", [])
    if not isinstance(achievement_ids, list) or not achievement_ids:
        return EMPTY_PROGRESS

    successes = database["succes"].find({"catList.id": {"$in": achievement_ids}})
    unlocked_list: list[str] = []
    total_points = 0

    async for category in successes:
        for success in category.get("catList", []):
            if success.get("id") not in achievement_ids:
                continue

            name = success.get("name")
            if isinstance(name, str):
                unlocked_list.append(name)
            total_points += int(success.get("value", 0))

    return {
        "unlockedList": unlocked_list,
        "totalPoints": total_points,
    }


async def get_calendar_events() -> list[dict[str, str]]:
    database = await get_database()
    cursor = database["events"].find({}, {"_id": 0}).sort([("date", 1), ("time", 1)])
    events: list[dict[str, str]] = []

    async for event in cursor:
        formatted_event = {
            "date": str(event.get("date", "")),
            "title": str(event.get("title", "")),
            "description": str(event.get("description", "")),
        }
        if event.get("time"):
            formatted_event["time"] = str(event["time"])
        events.append(formatted_event)

    return events


async def get_latest_newsletter() -> dict[str, str]:
    database = await get_database()
    newsletter = await database["newsletter"].find_one(
        {},
        {"_id": 0},
        sort=[("date", -1), ("created_at", -1)],
    )

    if newsletter is None:
        return {"date": "", "title": "", "content": ""}

    return {
        "date": str(newsletter.get("date", "")),
        "title": str(newsletter.get("title", "")),
        "content": str(newsletter.get("content", "")),
    }
