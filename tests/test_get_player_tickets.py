import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from get_player_tickets import get_all_player_ticket_counts, write_ticket_report


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.find_args = None

    def find(self, *args):
        self.find_args = args
        return iter(self.documents)


class PlayerTicketReportTests(unittest.TestCase):
    def test_lists_all_nonzero_players_sorted_by_total(self):
        users = FakeCollection(
            [
                {
                    "dofus_username": "Alpha",
                    "achievement": [10, 11, 10],
                    "bonus_ticket_count": 2,
                },
                {
                    "dofus_username": "Bravo",
                    "achievement": [],
                    "bonus_ticket_count": 8,
                },
                {
                    "dofus_username": "Zero",
                    "achievement": [],
                    "bonus_ticket_count": 0,
                },
            ]
        )
        successes = FakeCollection(
            [
                {"id": 10, "difficulte": "***"},
                {"id": 11, "difficulte": "*"},
            ]
        )

        result = get_all_player_ticket_counts(users, successes)

        self.assertEqual(
            [
                (player.dofus_username, player.total_tickets)
                for player in result
            ],
            [("Bravo", 8), ("Alpha", 6)],
        )

    def test_ignores_malformed_values_and_players_without_username(self):
        users = FakeCollection(
            [
                {
                    "dofus_username": "Valid",
                    "achievement": [10, True, "11"],
                    "bonus_ticket_count": "5",
                },
                {"achievement": [10], "bonus_ticket_count": 2},
            ]
        )
        successes = FakeCollection([{"id": 10, "difficulte": "**"}])

        result = get_all_player_ticket_counts(users, successes)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].dofus_username, "Valid")
        self.assertEqual(result[0].total_tickets, 2)

    def test_writes_utf8_text_report(self):
        users = FakeCollection(
            [
                {
                    "dofus_username": "Héros",
                    "achievement": [],
                    "bonus_ticket_count": 3,
                }
            ]
        )
        players = get_all_player_ticket_counts(users, FakeCollection([]))

        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "tickets.txt"
            write_ticket_report(players, output_path)
            content = output_path.read_text(encoding="utf-8")

        self.assertEqual(content, "Héros: 3 tickets (base: 0, bonus: 3)\n")


if __name__ == "__main__":
    unittest.main()
