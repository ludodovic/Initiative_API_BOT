# Initiative API Bot

## Commands

- Create a `.env` from `.env.example`; `app/config.py` reads it for local settings.
- Install dependencies with `pip install -r requirements.txt`.
- Run the API alone with `uvicorn app.api.main:app --reload`.
- Run the Discord bot alone with `python -m app.bot.main`.
- Run both with `python -m app.main`; use this for `POST /api/succes/claim`, which requires the bot in the same process.
- No automated test or lint command is configured. For a syntax-only check, run `python -m compileall app`.

## Architecture

- `app/api/main.py` owns the FastAPI routes; business and MongoDB operations live in `app/services/` and `app/db/mongodb.py`.
- MongoDB database and collection names are configuration/data contracts. The frontend depends on the `/api/*` response shapes in `app/api/main.py`.
- `app/bot/main.py` owns Discord commands and event handlers. The configured prefix defaults to `!`; staff authorization accepts the `Conseiller` and `Conseiller Intérimaire` roles.
- The website is in the sibling `../initiative-kourial.fr` repository. Its Angular `ApiService` is the client contract to update with API route or payload changes.

## Integration Constraints

- Authenticated frontend routes use `Authorization: Bearer <token>`; Discord registration creates and sends that token.
- Keep success identifiers numeric and consistent across `users.achievement`, `succes.catList[].id`, and `succes2.id`.
- Discord member, message-content, reactions, and voice-state intents must be enabled for the bot's registered handlers.
