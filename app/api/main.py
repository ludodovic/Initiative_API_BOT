from contextlib import asynccontextmanager
import logging

from typing import Any, Annotated

from fastapi import Body, FastAPI, File, Form, Header, UploadFile, status
from fastapi.responses import JSONResponse

from app.bot.claim_messages import post_success_claim_for_validation
from app.bot.runtime import get_bot
from app.db import close_mongo_client, get_database
from app.services import (
    create_success_claim,
    COMPANIONS,
    DraftError,
    TournamentError,
    can_access_tournament,
    create_team,
    create_tournament,
    delete_team,
    generate_bracket,
    get_draft,
    get_companion_catalog,
    get_active_draft_id,
    get_active_tournament_id,
    get_roster,
    get_tournament,
    get_calendar_events,
    get_latest_newsletter,
    get_success2_catalog,
    get_success_catalog,
    get_success_leaderboard,
    get_unlocked_successes,
    get_user_by_token,
    get_user_profile,
    get_user_validation_history,
    is_draft_admin,
    list_tournaments,
    present_draft,
    reset_draft,
    present_tournament,
    register_participant,
    record_winner,
    reset_to_registration,
    reset_to_team_building,
    remove_participant,
    lock_registration,
    select_companion,
    toss_coin,
    update_team,
    update_user_class,
)
from app.services.claim_service import validate_image_content_types
from app.services.success_validation_service import find_success


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_mongo_client()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Initiative API",
    description="Frontend API for Initiative homepage news and user success progress.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/api/companion-tournaments", status_code=status.HTTP_201_CREATED)
async def api_create_companion_tournament(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Create an empty companion tournament in the registration state."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    try:
        tournament = await create_tournament(payload)
    except TournamentError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=await present_tournament(tournament, user))


@app.post("/api/companion-tournaments/{tournament_id}/participants")
async def api_register_companion_tournament_participant(
    tournament_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Register an existing roster user while registration is open."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    try:
        tournament = await register_participant(tournament_id, payload.get("userId", payload.get("user_id")))
    except TournamentError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_tournament(tournament, user))


@app.delete("/api/companion-tournaments/{tournament_id}/participants/{user_id}")
async def api_remove_companion_tournament_participant(
    tournament_id: str,
    user_id: int,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Remove a registered roster user before registration is locked."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    try:
        tournament = await remove_participant(tournament_id, user_id)
    except TournamentError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_tournament(tournament, user))


@app.post("/api/companion-tournaments/{tournament_id}/lock-registration")
async def api_lock_companion_tournament_registration(
    tournament_id: str,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Lock the roster and move the tournament to manual team building."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    try:
        tournament = await lock_registration(tournament_id)
    except TournamentError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_tournament(tournament, user))


@app.post("/api/companion-tournaments/{tournament_id}/teams")
async def api_create_companion_tournament_team(
    tournament_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Create one complete, manually named team from registered users."""
    return await _tournament_team_mutation_response(tournament_id, payload, authorization, "create")


@app.put("/api/companion-tournaments/{tournament_id}/teams/{team_id}")
async def api_update_companion_tournament_team(
    tournament_id: str,
    team_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Replace a manual team while the tournament is in team building."""
    return await _tournament_team_mutation_response(tournament_id, payload, authorization, "update", team_id)


@app.delete("/api/companion-tournaments/{tournament_id}/teams/{team_id}")
async def api_delete_companion_tournament_team(
    tournament_id: str,
    team_id: str,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Delete a manual team while the tournament is in team building."""
    return await _tournament_team_mutation_response(tournament_id, {}, authorization, "delete", team_id)


@app.post("/api/companion-tournaments/{tournament_id}/generate")
async def api_generate_companion_tournament_bracket(
    tournament_id: str,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Validate complete teams, generate the bracket, and create ready 2v2 drafts."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    try:
        tournament = await generate_bracket(tournament_id)
    except TournamentError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_tournament(tournament, user))


@app.get("/api/companion-tournaments")
async def api_list_companion_tournaments(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """List normalized companion tournament brackets for authenticated users."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    tournaments = await list_tournaments(user)
    return JSONResponse(status_code=status.HTTP_200_OK, content=[await present_tournament(item, user) for item in tournaments])


@app.get("/api/companion-tournaments/{tournament_id}")
async def api_get_companion_tournament(
    tournament_id: str,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Return teams, participants, ordered rounds, match result statuses, and active 2v2 drafts."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    tournament = await get_tournament(tournament_id)
    if tournament is None:
        return _json_error(status.HTTP_404_NOT_FOUND, "Tournament not found")
    if not can_access_tournament(tournament, user):
        return _json_error(status.HTTP_403_FORBIDDEN, "You cannot access this tournament")
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_tournament(tournament, user))


@app.post("/api/companion-tournaments/{tournament_id}/matches/{match_id}/winner")
async def api_record_companion_tournament_winner(
    tournament_id: str,
    match_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Administratively record a ready match winner with optimistic `version` checking and atomic advancement."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    try:
        tournament = await record_winner(
            tournament_id,
            match_id,
            payload.get("winnerTeamId", payload.get("winner_team_id")),
            payload.get("version"),
        )
    except TournamentError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_tournament(tournament, user))


@app.post("/api/companion-tournaments/{tournament_id}/reset")
async def api_reset_companion_tournament(
    tournament_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Return a generated tournament to manual team composition and delete its linked drafts."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    try:
        tournament = await reset_to_team_building(tournament_id, payload.get("version"))
    except TournamentError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_tournament(tournament, user))


@app.post("/api/companion-tournaments/{tournament_id}/reset-registration")
async def api_reset_companion_tournament_registration(
    tournament_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Clear the locked roster and teams so registrations can start over."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    try:
        tournament = await reset_to_registration(tournament_id, payload.get("version"))
    except TournamentError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_tournament(tournament, user))


@app.get("/api/companion-drafts/access")
async def api_companion_draft_access(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Return the authenticated user's companion-draft access level."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    active_draft_id = await get_active_draft_id(user)
    active_tournament_id = await get_active_tournament_id(user)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "isAdmin": is_draft_admin(user),
            "activeDraftId": active_draft_id,
            "activeTournamentId": active_tournament_id,
            "canAccessPage": is_draft_admin(user) or active_draft_id is not None or active_tournament_id is not None,
        },
    )


@app.get("/api/companion-drafts/roster")
async def api_companion_draft_roster(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Return the non-sensitive user roster available to draft administrators."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return JSONResponse(status_code=status.HTTP_200_OK, content=await get_roster())


@app.get("/api/companion-drafts/companions")
async def api_companion_catalog(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Return the canonical DofusDB companion catalog used by drafts."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_companion_catalog())


@app.post("/api/companion-drafts/{draft_id}/coin-toss")
async def api_companion_draft_coin_toss(
    draft_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Perform the draft's one-time coin toss."""
    return await _draft_mutation_response(draft_id, payload, authorization, "coin_toss")


@app.post("/api/companion-drafts/{draft_id}/reset")
async def api_reset_companion_draft(
    draft_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Administratively reset a companion draft to its pre-toss state."""
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    draft = await get_draft(draft_id)
    if draft is None:
        return _json_error(status.HTTP_404_NOT_FOUND, "Draft not found")
    try:
        reset = await reset_draft(draft_id, payload.get("version"))
    except DraftError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_draft(reset, user))


@app.post("/api/companion-drafts/{draft_id}/ban")
async def api_companion_draft_ban(
    draft_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Ban a companion during the A-B-A-B ban phase."""
    return await _draft_mutation_response(draft_id, payload, authorization, "ban")


@app.post("/api/companion-drafts/{draft_id}/pick")
async def api_companion_draft_pick(
    draft_id: str,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Pick a companion during the B-A-B-A pick phase."""
    return await _draft_mutation_response(draft_id, payload, authorization, "pick")


@app.get("/api/succes/unlock")
async def api_unlocked_successes(authorization: str | None = Header(default=None)) -> dict:
    return await get_unlocked_successes(_extract_bearer_token(authorization))


@app.get("/api/succes")
async def api_success_catalog() -> list[dict]:
    return await get_success_catalog()


@app.get("/api/succes2")
async def api_success2_catalog() -> list[dict]:
    return await get_success2_catalog()


@app.get("/api/succes/leaderboard")
async def api_success_leaderboard() -> list[dict]:
    return await get_success_leaderboard()


@app.get("/api/succes/validations")
async def api_success_validations(authorization: str | None = Header(default=None)) -> JSONResponse:
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    history = await get_user_validation_history(str(user.get("discord_username", "")))
    return JSONResponse(status_code=status.HTTP_200_OK, content=history)


@app.get("/api/user")
async def api_user(authorization: str | None = Header(default=None)) -> JSONResponse:
    user = await get_user_profile(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    return JSONResponse(status_code=status.HTTP_200_OK, content=user)


@app.post("/api/user/class")
async def api_user_class(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    class_name = payload.get("class")
    if not isinstance(class_name, str):
        return _json_error(status.HTTP_400_BAD_REQUEST, "Class is required")

    user = await update_user_class(_extract_bearer_token(authorization), class_name)
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    return JSONResponse(status_code=status.HTTP_200_OK, content=user)


@app.post("/api/succes/claim")
async def api_claim_success(
    successId: str = Form(...),
    successName: str = Form(...),
    successDescription: str = Form(...),
    description: str = Form(default=""),
    images: Annotated[list[UploadFile], File()] = [],
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    try:
        success_id = int(successId)
    except ValueError:
        return _json_error(status.HTTP_400_BAD_REQUEST, "Unknown success")

    success_saisson = 1
    success = await find_success(str(success_id))
    if success is None:
        success_saisson = 2
        database = await get_database()
        success = await database["succes2"].find_one({"id": success_id})
        if success is None:
            return _json_error(status.HTTP_404_NOT_FOUND, "Unknown success")

    try:
        if success_saisson == 2 and not images:
            if images is None or len(images) == 0:
                image_payloads = []
        else:
            if not images:
                return _json_error(status.HTTP_400_BAD_REQUEST, "At least one image is required")
            selected_images = images[:3]
            content_types = [image.content_type or "" for image in selected_images]
            if not validate_image_content_types(content_types):
                return _json_error(status.HTTP_400_BAD_REQUEST, "Only PNG and JPG images are accepted")
            image_payloads = [
                (image.content_type or "", await image.read())
                for image in selected_images
            ]

        claim = await create_success_claim(
            user=user,
            success_id=success_id,
            success_name=successName,
            success_description=successDescription,
            description=description,
            images=image_payloads,
        )

        bot = get_bot()
        if bot is None:
            raise RuntimeError("Discord bot is not running in this process.")

        await post_success_claim_for_validation(bot, claim)
    except Exception as e:
        logger.info(f"Error occurred while creating claim: {e}")
        return _json_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to create claim")

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"ok": True, "claimId": claim["claimId"]},
    )


@app.get("/api/news/calendar")
async def api_calendar_events() -> list[dict[str, str]]:
    return await get_calendar_events()


@app.get("/api/news/letter")
async def api_latest_newsletter() -> dict[str, str]:
    return await get_latest_newsletter()


def _draft_teams_from_payload(payload: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    team_a = payload.get("teamAUserIds", payload.get("team_a_user_ids"))
    team_b = payload.get("teamBUserIds", payload.get("team_b_user_ids"))
    teams = payload.get("teams")
    if isinstance(teams, dict):
        team_a = teams.get("A", team_a)
        team_b = teams.get("B", team_b)
    user_ids = payload.get("userIds", payload.get("user_ids"))
    if isinstance(user_ids, list) and team_a is None and team_b is None:
        team_a, team_b = user_ids[:2], user_ids[2:]
    return team_a if isinstance(team_a, list) else [], team_b if isinstance(team_b, list) else []


async def _draft_mutation_response(
    draft_id: str,
    payload: dict[str, Any],
    authorization: str | None,
    action: str,
) -> JSONResponse:
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    version = payload.get("version")
    try:
        if action == "coin_toss":
            draft = await toss_coin(draft_id, user, version)
        else:
            companion_id = payload.get("companionId", payload.get("companion_id"))
            draft = await select_companion(draft_id, user, version, companion_id, action)
    except DraftError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_draft(draft, user))


async def _tournament_team_mutation_response(
    tournament_id: str,
    payload: dict[str, Any],
    authorization: str | None,
    action: str,
    team_id: str | None = None,
) -> JSONResponse:
    user = await get_user_by_token(_extract_bearer_token(authorization))
    if user is None:
        return _json_error(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not is_draft_admin(user):
        return _json_error(status.HTTP_403_FORBIDDEN, "Administrator access required")
    try:
        if action == "create":
            tournament = await create_team(tournament_id, payload)
        elif action == "update" and team_id is not None:
            tournament = await update_team(tournament_id, team_id, payload)
        elif action == "delete" and team_id is not None:
            tournament = await delete_team(tournament_id, team_id)
        else:
            return _json_error(status.HTTP_400_BAD_REQUEST, "Unknown team action")
    except TournamentError as error:
        return _json_error(error.status_code, error.message)
    return JSONResponse(status_code=status.HTTP_200_OK, content=await present_tournament(tournament, user))


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "message": message},
    )
