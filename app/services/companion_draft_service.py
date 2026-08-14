import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument

from app.config import get_settings
from app.db import get_database

DRAFT_COLLECTION = "companion_drafts"
USER_COLLECTION = "users"
BAN_TURNS = ("A", "B", "A", "B")
PICK_TURNS = ("B", "A", "B", "A")

# Canonical DofusDB companion ids and their French labels (52 entries).
COMPANIONS: dict[int, str] = {
    1: "Lumino", 2: "Skale", 6: "Masse", 7: "Scoreur", 8: "Korbax", 9: "Ombre",
    11: "Chevalier d'Astrub", 12: "Krosmoglob", 14: "Malle O'Kranh", 15: "Éclaireur spectral",
    16: "Toxine", 17: "Archiduk", 55: "Lumino Star", 56: "Ténèbre", 57: "Nuage",
    58: "Goutte", 59: "Feuille", 60: "Flamme", 61: "Riktus fine-lame", 62: "Riktus archer",
    63: "Riktus baroudeur", 64: "Riktus ensorceleuse", 65: "Grüt", 66: "Koksis",
    67: "Gobeuf", 68: "Laikteur", 69: "Rekto Topi", 70: "Grizou", 71: "Kloug",
    72: "Hulkrap", 73: "Klüme", 74: "Manitou Zoth", 75: "Rapine", 76: "Phong Huss",
    77: "Hectaupe", 78: "Grouillot", 79: "Karotz", 80: "Rapiat", 81: "Kubitus",
    82: "Piggy Paupe", 83: "Ougicle", 84: "Inferno", 85: "Styx", 86: "Mandrin",
    87: "Will Killson", 88: "Traçon", 89: "Mirh", 90: "Logram", 91: "Kalkanéus",
    92: "Hichète", 93: "Haku", 94: "Turyé",
}

# DofusPourLesNoobs does not consistently derive image paths from display names.
COMPANION_IMAGE_SLUGS: dict[str, str] = {
    "Koksis": "kocksis",
    "Phong Huss": "phong-uss",
    "Traçon": "tracon",
    "Tracon": "tracon",
}


class DraftError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def is_draft_admin(user: dict[str, Any]) -> bool:
    configured_names = get_settings().companion_draft_admins.split(",")
    admins = {name.strip().casefold() for name in configured_names if name.strip()}
    username = str(user.get("discord_username", "")).casefold()
    dofus_name = str(user.get("dofus_username", "")).casefold()
    return username in admins or dofus_name in admins


async def get_roster() -> list[dict[str, Any]]:
    database = await get_database()
    cursor = database[USER_COLLECTION].find(
        {"id": {"$type": "number"}, "discord_id": {"$type": "number"}},
        {"_id": 0, "id": 1, "dofus_username": 1, "class": 1},
    ).sort("id", 1)
    return [user async for user in cursor]


def get_companion_catalog() -> list[dict[str, Any]]:
    """Return companion display data with explicit known image slugs and a derived fallback."""
    return [
        {"id": companion_id, "name": name, "image": _companion_image_url(name)}
        for companion_id, name in COMPANIONS.items()
    ]


async def create_draft(
    team_a_user_ids: list[Any],
    team_b_user_ids: list[Any],
    tournament_id: str | None = None,
    match_id: str | None = None,
) -> dict[str, Any]:
    if not tournament_id or not match_id:
        raise DraftError(409, "Companion drafts are created only for an active tournament match")
    participant_ids = team_a_user_ids + team_b_user_ids
    if (
        len(team_a_user_ids) != 2
        or len(team_b_user_ids) != 2
        or any(not isinstance(user_id, int) or isinstance(user_id, bool) for user_id in participant_ids)
        or len(set(participant_ids)) != 4
    ):
        raise DraftError(400, "Exactly four unique numeric user ids are required, two per team")

    database = await get_database()
    tournament = await database["companion_tournaments"].find_one({"tournamentId": tournament_id}, {"_id": 0})
    match = next((item for item in (tournament or {}).get("matches", []) if item.get("matchId") == match_id), None)
    if (
        tournament is None
        or tournament.get("status") != "active"
        or tournament.get("teamSize") != 2
        or match is None
        or match.get("resultStatus") != "ready"
        or match.get("draftId") is not None
    ):
        raise DraftError(409, "The tournament match is not ready for a companion draft")
    teams = {team["teamId"]: team["participantIds"] for team in tournament.get("teams", [])}
    match_members = [teams.get(team_id) for team_id in match.get("teamIds", [])]
    if match_members != [team_a_user_ids, team_b_user_ids]:
        raise DraftError(409, "Draft participants do not match the tournament teams")
    found_ids = {
        user["id"]
        async for user in database[USER_COLLECTION].find(
            {"id": {"$in": participant_ids}}, {"_id": 0, "id": 1}
        )
    }
    if found_ids != set(participant_ids):
        raise DraftError(400, "All participant user ids must exist")

    active_draft = await database[DRAFT_COLLECTION].find_one(
        {
            "status": {"$ne": "complete"},
            "$or": [
                {"teamAUserIds": {"$in": participant_ids}},
                {"teamBUserIds": {"$in": participant_ids}},
            ],
        },
        {"_id": 0, "draftId": 1},
    )
    if active_draft is not None:
        raise DraftError(409, "A selected player is already in an active draft")

    document: dict[str, Any] = {
        "draftId": str(uuid4()),
        "teamAUserIds": team_a_user_ids,
        "teamBUserIds": team_b_user_ids,
        "status": "awaiting_coin_toss",
        "currentPhase": "coin_toss",
        "currentTeam": None,
        "coinToss": None,
        "bans": [],
        "picks": [],
        "usedCompanionIds": [],
        "tournamentId": tournament_id,
        "matchId": match_id,
        "version": 1,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await database[DRAFT_COLLECTION].insert_one(document)
    return _serialize(document)


async def get_draft(draft_id: str) -> dict[str, Any] | None:
    database = await get_database()
    document = await database[DRAFT_COLLECTION].find_one({"draftId": draft_id})
    return _serialize(document) if document else None


async def list_drafts(user: dict[str, Any]) -> list[dict[str, Any]]:
    database = await get_database()
    query: dict[str, Any] = {}
    if not is_draft_admin(user):
        user_id = user.get("id")
        if not isinstance(user_id, int):
            return []
        query = {"$or": [{"teamAUserIds": user_id}, {"teamBUserIds": user_id}]}
    cursor = database[DRAFT_COLLECTION].find(query, {"_id": 0}).sort("createdAt", -1)
    drafts = [_serialize(document) async for document in cursor]
    return [draft for draft in drafts if await _has_active_context(draft)]


async def get_active_draft_id(user: dict[str, Any]) -> str | None:
    drafts = await list_drafts(user)
    for draft in drafts:
        if draft.get("status") != "complete":
            return str(draft["draftId"])
    return None


async def present_draft(draft: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Return the UI state without exposing unrelated user data or draft internals."""
    database = await get_database()
    participant_ids = draft["teamAUserIds"] + draft["teamBUserIds"]
    users = {
        item["id"]: {
            "id": item["id"],
            "dofus_username": str(item.get("dofus_username", "Joueur inconnu")),
            "class": str(item.get("class", "undefined")),
        }
        async for item in database[USER_COLLECTION].find(
            {"id": {"$in": participant_ids}},
            {"_id": 0, "id": 1, "dofus_username": 1, "class": 1},
        )
    }
    bans = {int(entry["companionId"]) for entry in draft["bans"]}
    picks = {int(entry["companionId"]): str(entry["team"]) for entry in draft["picks"]}
    current_team = draft.get("currentTeam")
    user_id = user.get("id")
    can_act = (
        draft["status"] == "drafting"
        and isinstance(user_id, int)
        and user_id in draft.get(f"team{current_team}UserIds", [])
    )
    phase = str(draft["currentPhase"])
    return {
        "id": draft["draftId"],
        "status": draft["status"],
        "phase": phase,
        "version": draft["version"],
        "coinToss": draft["coinToss"],
        "currentTeam": current_team,
        "currentTurnLabel": _turn_label(draft),
        "canCoinToss": draft["status"] == "awaiting_coin_toss" and can_access_draft(draft, user),
        "canAct": can_act,
        "teams": [
            {
                "id": team_id,
                "name": f"Équipe {team_id}",
                "users": [users.get(member_id, {"id": member_id, "dofus_username": "Joueur inconnu", "class": "undefined"}) for member_id in draft[f"team{team_id}UserIds"]],
            }
            for team_id in ("A", "B")
        ],
        "companions": [
            {
                "id": companion_id,
                "name": name,
                "image": _companion_image_url(name),
                "status": "banned" if companion_id in bans else "picked" if companion_id in picks else "available",
                "teamId": picks.get(companion_id),
            }
            for companion_id, name in COMPANIONS.items()
        ],
    }


def can_access_draft(draft: dict[str, Any], user: dict[str, Any]) -> bool:
    return is_draft_admin(user) or user.get("id") in (
        draft.get("teamAUserIds", []) + draft.get("teamBUserIds", [])
    )


async def toss_coin(draft_id: str, user: dict[str, Any], version: Any) -> dict[str, Any]:
    draft = await _require_access(draft_id, user)
    version_number = _require_version(version)
    if draft["status"] != "awaiting_coin_toss":
        raise DraftError(409, "Coin toss has already occurred")
    result = secrets.choice(("heads", "tails"))
    initial_team = secrets.choice(("A", "B"))
    return await _atomic_update(
        draft_id,
        version_number,
        {"status": "awaiting_coin_toss"},
        {"$set": {"coinToss": result, "status": "drafting", "currentPhase": "ban", "currentTeam": initial_team}},
    )


async def select_companion(
    draft_id: str,
    user: dict[str, Any],
    version: Any,
    companion_id: Any,
    action: str,
) -> dict[str, Any]:
    draft = await _require_access(draft_id, user)
    version_number = _require_version(version)
    if action not in {"ban", "pick"}:
        raise DraftError(400, "Unknown draft action")
    if not isinstance(companion_id, int) or isinstance(companion_id, bool) or companion_id not in COMPANIONS:
        raise DraftError(400, "Unknown companion id")
    if draft["status"] != "drafting" or draft["currentPhase"] != action:
        raise DraftError(409, "This action is not available now")
    current_team = draft["currentTeam"]
    team_members = draft[f"team{current_team}UserIds"]
    if user.get("id") not in team_members:
        raise DraftError(403, "Only a member of the current team can act")

    actions = draft[f"{action}s"]
    turns = BAN_TURNS if action == "ban" else PICK_TURNS
    action_index = len(actions)
    if action_index >= len(turns):
        raise DraftError(409, "This phase is complete")
    next_phase, next_team, next_status = _next_turn(action, action_index)
    update = {
        "$push": {f"{action}s": {"team": current_team, "companionId": companion_id}},
        "$addToSet": {"usedCompanionIds": companion_id},
        "$set": {"currentPhase": next_phase, "currentTeam": next_team, "status": next_status},
    }
    return await _atomic_update(
        draft_id,
        version_number,
        {"status": "drafting", "currentPhase": action, "currentTeam": current_team, "usedCompanionIds": {"$ne": companion_id}},
        update,
    )


async def reset_draft(draft_id: str, version: Any) -> dict[str, Any]:
    """Reset a draft to its pre-toss state for administrator-controlled testing."""
    version_number = _require_version(version)
    draft = await get_draft(draft_id)
    if draft is None:
        raise DraftError(404, "Draft not found")
    if not await _has_active_context(draft):
        raise DraftError(409, "This draft no longer belongs to an active tournament match")
    return await _atomic_update(
        draft_id,
        version_number,
        {},
        {
            "$set": {
                "status": "awaiting_coin_toss",
                "currentPhase": "coin_toss",
                "currentTeam": None,
                "coinToss": None,
                "bans": [],
                "picks": [],
                "usedCompanionIds": [],
            }
        },
    )


async def _require_access(draft_id: str, user: dict[str, Any]) -> dict[str, Any]:
    draft = await get_draft(draft_id)
    if draft is None:
        raise DraftError(404, "Draft not found")
    if not await _has_active_context(draft):
        raise DraftError(409, "This draft no longer belongs to an active tournament match")
    if not can_access_draft(draft, user):
        raise DraftError(403, "You cannot access this draft")
    return draft


async def _has_active_context(draft: dict[str, Any]) -> bool:
    tournament_id = draft.get("tournamentId")
    match_id = draft.get("matchId")
    if not isinstance(tournament_id, str) or not isinstance(match_id, str):
        return False
    database = await get_database()
    tournament = await database["companion_tournaments"].find_one({"tournamentId": tournament_id}, {"_id": 0})
    if tournament is None or tournament.get("status") != "active":
        return False
    match = next((item for item in tournament.get("matches", []) if item.get("matchId") == match_id), None)
    if match is None or match.get("resultStatus") != "ready" or match.get("draftId") != draft.get("draftId"):
        return False
    teams = {team["teamId"]: team["participantIds"] for team in tournament.get("teams", [])}
    return [teams.get(team_id) for team_id in match.get("teamIds", [])] == [draft.get("teamAUserIds"), draft.get("teamBUserIds")]


def _require_version(version: Any) -> int:
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise DraftError(400, "A positive numeric version is required")
    return version


def _next_turn(action: str, action_index: int) -> tuple[str, str | None, str]:
    if action == "ban" and action_index == len(BAN_TURNS) - 1:
        return "pick", PICK_TURNS[0], "drafting"
    turns = BAN_TURNS if action == "ban" else PICK_TURNS
    if action == "pick" and action_index == len(PICK_TURNS) - 1:
        return "complete", None, "complete"
    return action, turns[action_index + 1], "drafting"


def _turn_label(draft: dict[str, Any]) -> str:
    if draft["status"] == "awaiting_coin_toss":
        return "Les équipes doivent lancer la pièce."
    if draft["status"] == "complete":
        return "Draft terminé."
    action = "bannir" if draft["currentPhase"] == "ban" else "choisir"
    return f"Équipe {draft['currentTeam']} doit {action} un compagnon."


def _companion_image_url(name: str) -> str:
    slug = COMPANION_IMAGE_SLUGS.get(name, (
        name.casefold()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ü", "u")
        .replace("'", "-")
        .replace(" ", "-")
    ))
    return (
        "https://www.dofuspourlesnoobs.com/uploads/1/3/0/1/13010384/"
        "custom_themes/586567114324766674/files/tutorials/companions/illus/"
        f"{slug}.png"
    )


async def _atomic_update(
    draft_id: str,
    version: int,
    expected: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    database = await get_database()
    query = {"draftId": draft_id, "version": version, **expected}
    update["$inc"] = {"version": 1}
    document = await database[DRAFT_COLLECTION].find_one_and_update(
        query, update, return_document=ReturnDocument.AFTER
    )
    if document is None:
        raise DraftError(409, "Draft changed; refresh and try again")
    return _serialize(document)


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "_id"}
