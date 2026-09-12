import argparse
import getpass
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pymongo import MongoClient
from pymongo.collection import Collection


DEFAULT_OUTPUT_PATH = Path("player_tickets.txt")


@dataclass(frozen=True)
class PlayerTicketCount:
    dofus_username: str
    base_tickets: int
    bonus_tickets: int

    @property
    def total_tickets(self) -> int:
        return self.base_tickets + self.bonus_tickets


def get_all_player_ticket_counts(
    users: Collection,
    successes: Collection,
) -> list[PlayerTicketCount]:
    user_documents = list(
        users.find(
            {},
            {
                "_id": 0,
                "dofus_username": 1,
                "achievement": 1,
                "bonus_ticket_count": 1,
            },
        )
    )
    achievement_ids = {
        achievement_id
        for user in user_documents
        for achievement_id in _integer_values(user.get("achievement"))
    }
    tickets_by_success_id = _get_ticket_values(successes, achievement_ids)

    ticket_counts = []
    for user in user_documents:
        dofus_username = user.get("dofus_username")
        if not isinstance(dofus_username, str) or not dofus_username.strip():
            continue

        unlocked_ids = set(_integer_values(user.get("achievement")))
        base_tickets = sum(
            tickets_by_success_id.get(success_id, 0)
            for success_id in unlocked_ids
        )
        bonus_tickets = _integer_or_zero(user.get("bonus_ticket_count"))
        ticket_count = PlayerTicketCount(
            dofus_username=dofus_username,
            base_tickets=base_tickets,
            bonus_tickets=bonus_tickets,
        )
        if ticket_count.total_tickets > 0:
            ticket_counts.append(ticket_count)

    return sorted(
        ticket_counts,
        key=lambda player: (-player.total_tickets, player.dofus_username.casefold()),
    )


def write_ticket_report(
    ticket_counts: Iterable[PlayerTicketCount], output_path: Path
) -> None:
    lines = [
        f"{player.dofus_username}: {player.total_tickets} tickets "
        f"(base: {player.base_tickets}, bonus: {player.bonus_tickets})"
        for player in ticket_counts
    ]
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _get_ticket_values(
    successes: Collection, achievement_ids: set[int]
) -> dict[int, int]:
    if not achievement_ids:
        return {}

    ticket_values = {}
    cursor = successes.find(
        {"id": {"$in": list(achievement_ids)}},
        {"_id": 0, "id": 1, "difficulte": 1},
    )
    for success in cursor:
        success_id = success.get("id")
        difficulty = success.get("difficulte")
        if isinstance(success_id, int) and isinstance(difficulty, str):
            ticket_values[success_id] = len(difficulty)
    return ticket_values


def _integer_values(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, int) and not isinstance(item, bool)
    ]


def _integer_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write ticket totals for every player with at least one ticket."
    )
    parser.add_argument(
        "--mongodb-uri",
        help="MongoDB connection URI; prompts securely when omitted",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("MONGODB_DATABASE", "initiative"),
        help="MongoDB database name (default: initiative)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Report path (default: {DEFAULT_OUTPUT_PATH})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mongodb_uri = args.mongodb_uri or os.getenv("MONGODB_URI")
    if not mongodb_uri:
        mongodb_uri = getpass.getpass("MongoDB URI: ")
    if not mongodb_uri:
        print("MongoDB URI is required.")
        return 2

    client = MongoClient(mongodb_uri)
    try:
        database = client[args.database]
        ticket_counts = get_all_player_ticket_counts(
            database["users"], database["succes2"]
        )
    finally:
        client.close()

    write_ticket_report(ticket_counts, args.output)
    print(f"Saved {len(ticket_counts)} players to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
