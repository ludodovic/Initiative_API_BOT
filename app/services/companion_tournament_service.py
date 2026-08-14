from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument

from app.db import get_database
from app.services.companion_draft_service import (
    DraftError,
    create_draft,
    get_draft,
    present_draft,
    is_draft_admin,
)

TOURNAMENT_COLLECTION = "companion_tournaments"
USER_COLLECTION = "users"


class TournamentError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


async def create_tournament(payload: dict[str, Any]) -> dict[str, Any]:
    team_size = payload.get("teamSize", payload.get("team_size"))
    format_name = payload.get("format", payload.get("type", "single_elimination"))
    if team_size != 2:
        raise TournamentError(400, "Companion tournaments require exactly two players per team")
    if format_name not in {"single_match", "single_elimination"}:
        raise TournamentError(400, "format must be single_match or single_elimination")
    if "teams" in payload:
        raise TournamentError(400, "Teams are added after registration is locked")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TournamentError(400, "name must be a non-empty string")
    database = await get_database()
    current = await database[TOURNAMENT_COLLECTION].find_one(
        {"status": {"$in": ["registration", "team_building", "active"]}}, {"_id": 0, "tournamentId": 1}
    )
    if current is not None:
        raise TournamentError(409, "Complete the current tournament before creating another one")
    tournament_id = str(uuid4())
    document: dict[str, Any] = {
        "tournamentId": tournament_id,
        "name": name.strip(),
        "format": format_name,
        "teamSize": team_size,
        "status": "registration",
        "registeredParticipantIds": [],
        "teams": [],
        "matches": [],
        "version": 1,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await database[TOURNAMENT_COLLECTION].insert_one(document)
    return _serialize(document)


async def get_tournament(tournament_id: str) -> dict[str, Any] | None:
    database = await get_database()
    document = await database[TOURNAMENT_COLLECTION].find_one({"tournamentId": tournament_id})
    return _serialize(document) if document else None


async def list_tournaments(user: dict[str, Any]) -> list[dict[str, Any]]:
    database = await get_database()
    query: dict[str, Any] = {}
    if not is_draft_admin(user):
        user_id = user.get("id")
        if not isinstance(user_id, int):
            return []
        query = {"$or": [{"registeredParticipantIds": user_id}, {"teams.participantIds": user_id}]}
    cursor = database[TOURNAMENT_COLLECTION].find(query, {"_id": 0}).sort("createdAt", -1)
    return [_serialize(document) async for document in cursor]


async def get_active_tournament_id(user: dict[str, Any]) -> str | None:
    """Return the one unfinished tournament that the authenticated user may view."""
    tournaments = await list_tournaments(user)
    return next((str(item["tournamentId"]) for item in tournaments if item["status"] != "complete"), None)


def can_access_tournament(tournament: dict[str, Any], user: dict[str, Any]) -> bool:
    """Allow administrators and registered tournament participants to view a bracket."""
    user_id = user.get("id")
    return is_draft_admin(user) or (
        isinstance(user_id, int)
        and (
            user_id in tournament.get("registeredParticipantIds", [])
            or any(user_id in team["participantIds"] for team in tournament.get("teams", []))
        )
    )


async def register_participant(tournament_id: str, user_id: Any) -> dict[str, Any]:
    if not _is_user_id(user_id):
        raise TournamentError(400, "userId must be a numeric user id")
    tournament = await _require_tournament(tournament_id, "registration")
    if user_id in tournament.get("registeredParticipantIds", []):
        raise TournamentError(409, "User is already registered")
    await _validate_user_ids([user_id])
    tournament["registeredParticipantIds"].append(user_id)
    return await _save_tournament(tournament)


async def remove_participant(tournament_id: str, user_id: Any) -> dict[str, Any]:
    if not _is_user_id(user_id):
        raise TournamentError(400, "userId must be a numeric user id")
    tournament = await _require_tournament(tournament_id, "registration")
    if user_id not in tournament.get("registeredParticipantIds", []):
        raise TournamentError(404, "Registered user not found")
    tournament["registeredParticipantIds"].remove(user_id)
    return await _save_tournament(tournament)


async def lock_registration(tournament_id: str) -> dict[str, Any]:
    tournament = await _require_tournament(tournament_id, "registration")
    participant_count = len(tournament["registeredParticipantIds"])
    minimum_count = tournament["teamSize"] * (2 if tournament["format"] == "single_match" else 4)
    maximum_count = tournament["teamSize"] * (2 if tournament["format"] == "single_match" else 8)
    if participant_count < minimum_count or participant_count > maximum_count or participant_count % tournament["teamSize"]:
        raise TournamentError(400, "Registration count does not match the selected tournament format")
    tournament["status"] = "team_building"
    return await _save_tournament(tournament)


async def create_team(tournament_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    tournament = await _require_tournament(tournament_id, "team_building")
    team = _parse_team(payload, tournament["teamSize"])
    _validate_team_members(tournament, team, None)
    tournament["teams"].append(team)
    return await _save_tournament(tournament)


async def update_team(tournament_id: str, team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    tournament = await _require_tournament(tournament_id, "team_building")
    index = next((i for i, team in enumerate(tournament["teams"]) if team["teamId"] == team_id), None)
    if index is None:
        raise TournamentError(404, "Team not found")
    team = _parse_team(payload, tournament["teamSize"], team_id)
    _validate_team_members(tournament, team, team_id)
    tournament["teams"][index] = team
    return await _save_tournament(tournament)


async def delete_team(tournament_id: str, team_id: str) -> dict[str, Any]:
    tournament = await _require_tournament(tournament_id, "team_building")
    teams = [team for team in tournament["teams"] if team["teamId"] != team_id]
    if len(teams) == len(tournament["teams"]):
        raise TournamentError(404, "Team not found")
    tournament["teams"] = teams
    return await _save_tournament(tournament)


async def generate_bracket(tournament_id: str) -> dict[str, Any]:
    tournament = await _require_tournament(tournament_id, "team_building")
    _validate_generation(tournament)
    tournament["matches"] = _build_matches(tournament_id, tournament["teams"], tournament["format"])
    _resolve_byes(tournament)
    tournament = await _save_tournament(tournament)
    return await _ensure_ready_drafts(tournament)


async def reset_to_team_building(tournament_id: str, version: Any) -> dict[str, Any]:
    """Discard the generated bracket and linked drafts while retaining registrations and teams."""
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise TournamentError(400, "A positive numeric version is required")
    tournament = await get_tournament(tournament_id)
    if tournament is None:
        raise TournamentError(404, "Tournament not found")
    if tournament.get("status") != "active":
        raise TournamentError(409, "Only a generated tournament can return to team building")
    tournament["status"] = "team_building"
    tournament["matches"] = []
    tournament["version"] = version + 1
    database = await get_database()
    saved = await database[TOURNAMENT_COLLECTION].find_one_and_replace(
        {"tournamentId": tournament_id, "version": version},
        tournament,
        return_document=ReturnDocument.AFTER,
    )
    if saved is None:
        raise TournamentError(409, "Tournament changed; refresh and try again")
    await database["companion_drafts"].delete_many({"tournamentId": tournament_id})
    return _serialize(saved)


async def reset_to_registration(tournament_id: str, version: Any) -> dict[str, Any]:
    """Clear a locked roster and return a tournament to its registration phase."""
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise TournamentError(400, "A positive numeric version is required")
    tournament = await get_tournament(tournament_id)
    if tournament is None:
        raise TournamentError(404, "Tournament not found")
    if tournament.get("status") != "team_building":
        raise TournamentError(409, "Only team composition can return to registration")
    tournament["status"] = "registration"
    tournament["registeredParticipantIds"] = []
    tournament["teams"] = []
    tournament["version"] = version + 1
    database = await get_database()
    saved = await database[TOURNAMENT_COLLECTION].find_one_and_replace(
        {"tournamentId": tournament_id, "version": version},
        tournament,
        return_document=ReturnDocument.AFTER,
    )
    if saved is None:
        raise TournamentError(409, "Tournament changed; refresh and try again")
    return _serialize(saved)


async def record_winner(
    tournament_id: str, match_id: str, winner_team_id: Any, version: Any
) -> dict[str, Any]:
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise TournamentError(400, "A positive numeric version is required")
    if not isinstance(winner_team_id, str):
        raise TournamentError(400, "winnerTeamId is required")
    tournament = await get_tournament(tournament_id)
    if tournament is None:
        raise TournamentError(404, "Tournament not found")
    if tournament["status"] != "active":
        raise TournamentError(409, "Only an active tournament can receive a winner")
    match = next((item for item in tournament["matches"] if item["matchId"] == match_id), None)
    if match is None:
        raise TournamentError(404, "Match not found")
    if match["resultStatus"] != "ready":
        raise TournamentError(409, "Only a ready match can receive a winner")
    if winner_team_id not in match["teamIds"]:
        raise TournamentError(400, "Winner must be one of the match teams")
    if tournament["teamSize"] == 2:
        if not match.get("draftId"):
            raise TournamentError(409, "A linked companion draft is required before recording this result")
        draft = await get_draft(str(match["draftId"]))
        if (
            draft is None
            or draft.get("status") != "complete"
            or draft.get("tournamentId") != tournament_id
            or draft.get("matchId") != match_id
        ):
            raise TournamentError(409, "The linked companion draft must be complete first")

    updated = _serialize(tournament)
    updated_match = next(item for item in updated["matches"] if item["matchId"] == match_id)
    updated_match["winnerTeamId"] = winner_team_id
    updated_match["resultStatus"] = "complete"
    updated_match["completedAt"] = datetime.now(timezone.utc).isoformat()
    _propagate_winner(updated, updated_match)
    _resolve_byes(updated)
    updated["status"] = "complete" if _has_champion(updated) else "active"
    updated["version"] = version + 1

    database = await get_database()
    saved = await database[TOURNAMENT_COLLECTION].find_one_and_replace(
        {"tournamentId": tournament_id, "version": version},
        updated,
        return_document=ReturnDocument.AFTER,
    )
    if saved is None:
        raise TournamentError(409, "Tournament changed; refresh and try again")
    return await _ensure_ready_drafts(_serialize(saved))


async def present_tournament(tournament: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    database = await get_database()
    participant_ids = tournament.get("registeredParticipantIds")
    if participant_ids is None:
        participant_ids = [member_id for team in tournament.get("teams", []) for member_id in team["participantIds"]]
    users = {
        item["id"]: {"id": item["id"], "dofus_username": str(item.get("dofus_username", "Joueur inconnu")), "class": str(item.get("class", "undefined"))}
        async for item in database[USER_COLLECTION].find(
            {"id": {"$in": participant_ids}}, {"_id": 0, "id": 1, "dofus_username": 1, "class": 1}
        )
    }
    teams = [
        {**team, "participants": [users.get(member_id, {"id": member_id, "dofus_username": "Joueur inconnu", "class": "undefined"}) for member_id in team["participantIds"]]}
        for team in tournament["teams"]
    ]
    draft_states: dict[str, dict[str, Any]] = {}
    for match in tournament.get("matches", []):
        draft_id = match.get("draftId")
        if not draft_id:
            continue
        draft = await get_draft(str(draft_id))
        if draft is not None:
            draft_states[str(draft_id)] = await present_draft(draft, user)
    rounds: dict[int, list[dict[str, Any]]] = {}
    for match in tournament.get("matches", []):
        item = {key: value for key, value in match.items() if key != "nextMatchId"}
        if match.get("draftId") in draft_states:
            item["draft"] = draft_states[match["draftId"]]
        rounds.setdefault(match["round"], []).append(item)
    return {
        "id": tournament["tournamentId"], "name": tournament["name"], "format": tournament["format"],
        "teamSize": tournament["teamSize"], "status": tournament["status"], "version": tournament["version"],
        "teams": teams,
        "participants": [users.get(member_id, {"id": member_id, "dofus_username": "Joueur inconnu", "class": "undefined"}) for member_id in participant_ids],
        "registeredParticipants": [users.get(member_id, {"id": member_id, "dofus_username": "Joueur inconnu", "class": "undefined"}) for member_id in participant_ids],
        "rounds": [{"number": number, "matches": matches} for number, matches in sorted(rounds.items())] if tournament["status"] in {"active", "complete"} else [],
    }


async def _require_tournament(tournament_id: str, expected_status: str) -> dict[str, Any]:
    tournament = await get_tournament(tournament_id)
    if tournament is None:
        raise TournamentError(404, "Tournament not found")
    if tournament.get("status") != expected_status:
        raise TournamentError(409, f"Tournament is not in {expected_status} state")
    return tournament


async def _save_tournament(tournament: dict[str, Any]) -> dict[str, Any]:
    version = tournament["version"]
    tournament["version"] = version + 1
    database = await get_database()
    saved = await database[TOURNAMENT_COLLECTION].find_one_and_replace(
        {"tournamentId": tournament["tournamentId"], "version": version},
        tournament,
        return_document=ReturnDocument.AFTER,
    )
    if saved is None:
        raise TournamentError(409, "Tournament changed; refresh and try again")
    return _serialize(saved)


def _is_user_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


async def _validate_user_ids(user_ids: list[int]) -> None:
    database = await get_database()
    found = {item["id"] async for item in database[USER_COLLECTION].find({"id": {"$in": user_ids}}, {"_id": 0, "id": 1})}
    if found != set(user_ids):
        raise TournamentError(400, "All participant user ids must exist")


def _parse_team(payload: dict[str, Any], team_size: int, team_id: str | None = None) -> dict[str, Any]:
    member_ids = payload.get("participantIds", payload.get("userIds", payload.get("members")))
    if not isinstance(member_ids, list) or len(member_ids) != team_size or any(not _is_user_id(member_id) for member_id in member_ids):
        raise TournamentError(400, f"Each team must contain exactly {team_size} numeric participant ids")
    if len(set(member_ids)) != team_size:
        raise TournamentError(400, "A team cannot contain the same participant twice")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TournamentError(400, "Team name must be a non-empty string")
    return {"teamId": team_id or str(uuid4()), "name": name.strip(), "participantIds": member_ids}


def _validate_team_members(tournament: dict[str, Any], team: dict[str, Any], replacing_team_id: str | None) -> None:
    registered_ids = set(tournament.get("registeredParticipantIds", []))
    if not set(team["participantIds"]).issubset(registered_ids):
        raise TournamentError(400, "Team members must be registered participants")
    assigned_ids = {
        member_id
        for existing_team in tournament["teams"]
        if existing_team["teamId"] != replacing_team_id
        for member_id in existing_team["participantIds"]
    }
    if assigned_ids.intersection(team["participantIds"]):
        raise TournamentError(400, "Participants may only appear on one team")


def _validate_generation(tournament: dict[str, Any]) -> None:
    teams = tournament["teams"]
    team_count = len(teams)
    if any(len(team.get("participantIds", [])) != tournament["teamSize"] for team in teams):
        raise TournamentError(400, "Each team must contain exactly the tournament teamSize")
    required_count = 2 if tournament["format"] == "single_match" else None
    if required_count is not None and team_count != required_count:
        raise TournamentError(400, "A single match requires exactly two complete teams")
    if tournament["format"] == "single_elimination" and not 4 <= team_count <= 8:
        raise TournamentError(400, "A single-elimination tournament requires four to eight complete teams")
    assigned_ids = [member_id for team in teams for member_id in team["participantIds"]]
    registered_ids = tournament.get("registeredParticipantIds", [])
    if len(assigned_ids) != len(set(assigned_ids)) or set(assigned_ids) != set(registered_ids):
        raise TournamentError(400, "Every registered participant must be assigned to exactly one team")


def _parse_teams(raw_teams: list[Any], team_size: int) -> list[dict[str, Any]]:
    teams: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, raw_team in enumerate(raw_teams, start=1):
        if not isinstance(raw_team, dict):
            raise TournamentError(400, "Each team must be an object")
        member_ids = raw_team.get("participantIds", raw_team.get("userIds", raw_team.get("members")))
        if not isinstance(member_ids, list) or len(member_ids) != team_size or any(not isinstance(item, int) or isinstance(item, bool) for item in member_ids):
            raise TournamentError(400, f"Each team must contain exactly {team_size} numeric participant ids")
        if len(set(member_ids)) != team_size or seen.intersection(member_ids):
            raise TournamentError(400, "Participants may only appear on one team")
        seen.update(member_ids)
        name = raw_team.get("name", f"Équipe {index}")
        if not isinstance(name, str) or not name.strip():
            raise TournamentError(400, "Team name must be a non-empty string")
        teams.append({"teamId": str(uuid4()), "name": name.strip(), "participantIds": member_ids})
    return teams


async def _validate_participants(teams: list[dict[str, Any]]) -> None:
    participant_ids = [member_id for team in teams for member_id in team["participantIds"]]
    database = await get_database()
    found = {item["id"] async for item in database[USER_COLLECTION].find({"id": {"$in": participant_ids}}, {"_id": 0, "id": 1})}
    if found != set(participant_ids):
        raise TournamentError(400, "All participant user ids must exist")


def _build_matches(tournament_id: str, teams: list[dict[str, Any]], format_name: str) -> list[dict[str, Any]]:
    if format_name == "single_match":
        return [_new_match(1, 1, [teams[0]["teamId"], teams[1]["teamId"]])]
    bracket_size = 4 if len(teams) <= 4 else 8
    seeded = [team["teamId"] for team in teams] + [None] * (bracket_size - len(teams))
    # Seed first versus last so empty slots become explicit byes.
    seeded = [seeded[index] for pair in zip(range(bracket_size // 2), range(bracket_size - 1, bracket_size // 2 - 1, -1)) for index in pair]
    matches: list[dict[str, Any]] = []
    current_count = bracket_size // 2
    round_number = 1
    first_round_ids: list[str] = []
    for position in range(current_count):
        match = _new_match(round_number, position + 1, seeded[position * 2:position * 2 + 2])
        matches.append(match)
        first_round_ids.append(match["matchId"])
    previous_ids = first_round_ids
    while len(previous_ids) > 1:
        round_number += 1
        current_ids: list[str] = []
        for position in range(len(previous_ids) // 2):
            match = _new_match(round_number, position + 1, [None, None])
            matches.append(match)
            current_ids.append(match["matchId"])
            for slot, source_id in enumerate(previous_ids[position * 2:position * 2 + 2]):
                source = next(item for item in matches if item["matchId"] == source_id)
                source["nextMatchId"] = match["matchId"]
                source["nextSlot"] = slot
        previous_ids = current_ids
    return matches


def _new_match(round_number: int, position: int, team_ids: list[str | None]) -> dict[str, Any]:
    return {"matchId": str(uuid4()), "round": round_number, "position": position, "teamIds": team_ids, "resultStatus": "ready" if all(team_ids) else "pending", "winnerTeamId": None, "draftId": None, "nextMatchId": None, "nextSlot": None}


def _propagate_winner(tournament: dict[str, Any], match: dict[str, Any]) -> None:
    if not match.get("nextMatchId"):
        return
    next_match = next(item for item in tournament["matches"] if item["matchId"] == match["nextMatchId"])
    next_match["teamIds"][int(match["nextSlot"])] = match["winnerTeamId"]
    if all(next_match["teamIds"]):
        next_match["resultStatus"] = "ready"


def _resolve_byes(tournament: dict[str, Any]) -> None:
    changed = True
    while changed:
        changed = False
        for match in tournament["matches"]:
            teams = [team_id for team_id in match["teamIds"] if team_id]
            if (
                match["resultStatus"] == "pending"
                and len(teams) == 1
                and not _has_unresolved_source(tournament, match)
            ):
                match["winnerTeamId"] = teams[0]
                match["resultStatus"] = "bye"
                _propagate_winner(tournament, match)
                changed = True
    tournament["status"] = "complete" if _has_champion(tournament) else "active"


def _has_champion(tournament: dict[str, Any]) -> bool:
    final_round = max(match["round"] for match in tournament["matches"])
    final_match = next(match for match in tournament["matches"] if match["round"] == final_round)
    return final_match["resultStatus"] in {"complete", "bye"}


def _has_unresolved_source(tournament: dict[str, Any], match: dict[str, Any]) -> bool:
    """Do not turn a final into a bye while its other feeder match is still playable."""
    for slot, team_id in enumerate(match["teamIds"]):
        if team_id is not None:
            continue
        source = next(
            (
                item
                for item in tournament["matches"]
                if item.get("nextMatchId") == match["matchId"] and item.get("nextSlot") == slot
            ),
            None,
        )
        if source is not None and source["resultStatus"] not in {"complete", "bye"}:
            return True
    return False


async def _ensure_ready_drafts(tournament: dict[str, Any]) -> dict[str, Any]:
    if tournament["teamSize"] != 2 or tournament["status"] != "active":
        return tournament
    database = await get_database()
    for match in tournament["matches"]:
        if match["resultStatus"] != "ready" or match.get("draftId"):
            continue
        team_lookup = {team["teamId"]: team for team in tournament["teams"]}
        first, second = (team_lookup[team_id] for team_id in match["teamIds"])
        try:
            draft = await create_draft(first["participantIds"], second["participantIds"], tournament["tournamentId"], match["matchId"])
        except DraftError as error:
            raise TournamentError(error.status_code, error.message) from error
        saved = await database[TOURNAMENT_COLLECTION].find_one_and_update(
            {"tournamentId": tournament["tournamentId"], "version": tournament["version"], f"matches.matchId": match["matchId"], "matches.draftId": None},
            {"$set": {"matches.$.draftId": draft["draftId"]}, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if saved is None:
            latest = await get_tournament(tournament["tournamentId"])
            if latest is None:
                raise TournamentError(404, "Tournament not found")
            return latest
        tournament = _serialize(saved)
    return tournament


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "_id"}
