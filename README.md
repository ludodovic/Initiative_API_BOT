# Initiative API Bot

Python app that connects to a MongoDB database named `initiative`, exposes the frontend API routes, and runs a Discord bot for user registration.

## Collections

The MongoDB connector targets these collections:

- `events`
- `newsletter`
- `succes`
- `users`

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Update `.env` with your MongoDB URI and Discord bot token.

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

The bot currently exposes one admin command:

```text
!register_message #channel Your registration message here
```

The bot posts the message in the chosen channel, reacts with the server emoji `:Initiative_blason:`, and listens for users reacting with the same emoji. When a user reacts, it creates a document in the `users` collection:

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

## Run Both in One Process

```powershell
python -m app.main
```

## API Routes

The API exposes only the frontend routes used by the Angular app:

- `GET /api/succes/unlock`
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
