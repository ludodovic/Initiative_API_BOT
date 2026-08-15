# Initiative API Bot

Python app that connects to a configured MongoDB database, exposes the frontend API routes, and runs a Discord bot for user registration.

## Collections

The MongoDB connector targets these collections:

- `events`
- `newsletter`
- `succes`
- `users`
- `companion_drafts`
- `companion_tournaments` (embedded bracket matches, teams, and version)

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Update `.env` with your MongoDB URI and Discord bot token.

## Local Companion Draft Startup

Start the local-only MongoDB and FastAPI containers, then seed development users. MongoDB and the API are bound only to `127.0.0.1`; MongoDB uses the `initiative_dev` database and persists data in the `initiative_dev_mongo_data` Docker volume.

```text
make dev
```

The local stack supplies its own MongoDB configuration; do not put a production URI or credentials in `.env` for this workflow.

Useful targets: `make up`, `make seed`, `make logs`, `make down`, and `make clean` (which deletes local MongoDB data).

Use these development-only bearer tokens for the seeded users. They are fixtures, not Discord or user-provided tokens.

| User | ID | Token |
| --- | ---: | --- |
| Coccinelle | 42 | `development-only-coccinelle-token` |
| Ludzu | 1 | `development-only-ludzu-token` |
| Mynni | 3 | `development-only-mynni-token` |
| Testeur | 4 | `development-only-testeur-token` |

## Run the API

```powershell
uvicorn app.api.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

## Run the Discord Bot

```powershell
python -m app.bot.main
```

## Bot Usage

The bot registration command is reserved for members with the `Conseiller` role:

```text
!register_message #channel Your registration message here
```

The bot posts the message in the chosen channel, reacts with the server emoji `:Initiative:`, and listens for users reacting with the same emoji. When a user reacts, it creates a document in the `users` collection:

```json
{
  "id": 1,
  "discord_username": "name#0000",
  "dofus_username": "server nickname",
  "roles": ["Role A", "Role B"],
  "achievement": [],
  "token": "unique-authentication-token"
}
```

Then it sends the user a private Discord message with:

```text
https://initiative-kourial.fr?token=TOKEN_GENERATED
```

The bot needs Discord member and message content intents enabled in the Discord Developer Portal.

Configure the success validation channel:

```text
!set_validation_channel #channel
```

Declare a completed success with a prefix command:

```text
!succes Success name or number @member @member
!succes_accompli Success name or number @member @member
```

The command author is always included automatically. Success names with spaces are supported. If the success is given as a number, the bot searches `catList[].id`. Otherwise, it resolves the typed text against the configured success-name list, then searches `catList[].name`. Category names are not used as command input.

Users can also use the visible Discord slash command:

```text
/succes_accompli
```

Set `DISCORD_GUILD_ID` in `.env` to your server id if you want this slash command to appear quickly during deployment. If it is left as `0`, Discord global command sync can take longer.

The bot creates one pending validation message per user in the configured validation channel. Members with the `Conseiller` role can approve with the green check reaction or refuse with the red cross reaction. Approved validations add the success id to the user's `achievement` list.

## Run Both in One Process

```powershell
python -m app.main
```

## API Routes

The API exposes only the frontend routes used by the Angular app:

- `GET /api/succes/unlock`
- `GET /api/succes`
- `GET /api/succes/leaderboard`
- `POST /api/succes/claim`
- `GET /api/user`
- `POST /api/user/class`
- `GET /api/news/calendar`
- `GET /api/news/letter`

`GET /api/succes/unlock` reads the token from:

```text
Authorization: Bearer TOKEN
```

If the token is missing or invalid, the API returns:

```json
{
  "unlockedList": [],
  "totalPoints": 0
}
```

Success progress is computed from the authenticated user's `achievement` ids and the matching documents in the `succes` collection. Calendar events are read from `events`, and the latest newsletter is read from `newsletter`.
`GET /api/succes` returns the full `succes` collection without MongoDB `_id` fields.
`GET /api/succes/leaderboard` returns users sorted by total points descending.

`POST /api/succes/claim` is authenticated with `Authorization: Bearer TOKEN` and accepts `multipart/form-data`:

- `successId`
- `successName`
- `successDescription`
- `description`
- `images`

The API accepts PNG and JPG/JPEG images, keeps only the first 3 images, resizes them to a reasonable size, stores the claim in MongoDB, and posts the validation request with image attachments in the configured Discord validation channel. This route requires running API and bot together with `python -m app.main`, and `DISCORD_GUILD_ID` must be set.

`GET /api/user` returns the authenticated user's `dofus_username` and `class`. If `class` is missing in MongoDB, the response value is `"undefined"`.

`POST /api/user/class` updates the authenticated user's `class` field. The request body is JSON:

```json
{
  "class": "Cra"
}
```

## Companion Tournaments

All companion tournament routes require `Authorization: Bearer TOKEN`. Creation and winner recording require a configured companion draft administrator.

- `POST /api/companion-tournaments` creates manual teams. `teamSize` is `1`, `2`, or `3`; `format` is `single_match` (exactly two teams) or `single_elimination` (four to eight teams). Non-power-of-two brackets resolve byes server-side.
- `GET /api/companion-tournaments` lists normalized brackets.
- `GET /api/companion-tournaments/{tournamentId}` returns teams, resolved participants, ordered rounds/matches, result statuses, and the active linked draft for ready 2v2 matches.
- `POST /api/companion-tournaments/{tournamentId}/matches/{matchId}/winner` is administrator-only. It requires `{ "winnerTeamId": "...", "version": 1 }`; the versioned update records the result and advances the winner atomically in the tournament document.

Create payload example:

```json
{
  "name": "Tournoi du soir",
  "format": "single_elimination",
  "teamSize": 2,
  "teams": [
    { "name": "Équipe A", "participantIds": [1, 3] },
    { "name": "Équipe B", "participantIds": [4, 42] },
    { "name": "Équipe C", "participantIds": [5, 6] },
    { "name": "Équipe D", "participantIds": [7, 8] }
  ]
}
```

`resultStatus` is `pending`, `ready`, `bye`, or `complete`. A ready 2v2 match receives a linked companion draft automatically; its draft must be complete before an administrator may record the match winner. Team and participant IDs are server-generated/user collection IDs respectively. The companion catalog now includes `image`; known DofusPourLesNoobs path exceptions are Koksis (`kocksis`), Phong Huss (`phong-uss`), and Tracon/Traçon (`tracon`), with a normalized-name fallback for the remaining companions.
