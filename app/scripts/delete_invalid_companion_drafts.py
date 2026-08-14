"""Delete drafts that are not linked to their tournament match.

Run with --apply only after backing up the configured MongoDB database.
"""

import argparse
import asyncio

from app.db import close_mongo_client, get_database


async def delete_invalid_drafts(apply: bool) -> int:
    """Return the number of standalone or orphaned draft records found."""
    database = await get_database()
    invalid_ids: list[str] = []
    try:
        async for draft in database["companion_drafts"].find({}, {"_id": 0}):
            tournament_id = draft.get("tournamentId")
            match_id = draft.get("matchId")
            tournament = await database["companion_tournaments"].find_one(
                {"tournamentId": tournament_id}, {"_id": 0, "matches": 1, "teams": 1}
            ) if isinstance(tournament_id, str) else None
            match = next((item for item in (tournament or {}).get("matches", []) if item.get("matchId") == match_id), None)
            teams = {team["teamId"]: team["participantIds"] for team in (tournament or {}).get("teams", [])}
            valid_members = match is not None and [teams.get(team_id) for team_id in match.get("teamIds", [])] == [draft.get("teamAUserIds"), draft.get("teamBUserIds")]
            if not valid_members or match.get("draftId") != draft.get("draftId"):
                invalid_ids.append(str(draft["draftId"]))
        if apply and invalid_ids:
            await database["companion_drafts"].delete_many({"draftId": {"$in": invalid_ids}})
    finally:
        await close_mongo_client()
    return len(invalid_ids)


def main() -> None:
    """Run the maintenance task in dry-run mode unless --apply is supplied."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Delete invalid records instead of only counting them")
    arguments = parser.parse_args()
    count = asyncio.run(delete_invalid_drafts(arguments.apply))
    print(f"{'Deleted' if arguments.apply else 'Found'} {count} invalid companion draft(s).")


if __name__ == "__main__":
    main()
