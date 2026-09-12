import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import user_registration_service


class FakeRole:
    def __init__(self, name):
        self.name = name


class FakeMember:
    def __init__(
        self,
        member_id,
        username,
        display_name,
        roles,
        joined_at,
        *,
        nick=None,
        bot=False,
    ):
        self.id = member_id
        self.username = username
        self.display_name = display_name
        self.nick = nick
        self.roles = [FakeRole("@everyone"), *[FakeRole(role) for role in roles]]
        self.joined_at = joined_at
        self.bot = bot

    def __str__(self):
        return self.username


class FakeGuild:
    def __init__(self, members):
        self.members_to_fetch = members

    def fetch_members(self, *, limit):
        self.requested_limit = limit

        async def iterator():
            for member in self.members_to_fetch:
                yield member

        return iterator()


class FakeUsersCollection:
    def __init__(self, documents):
        self.documents = documents

    async def find_one(self, query=None, *, sort=None):
        if sort is not None:
            return max(self.documents, key=lambda user: user.get("id", 0), default=None)
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None

    async def update_one(self, query, update):
        document = await self.find_one(query)
        new_values = update["$set"]
        changed = any(document.get(key) != value for key, value in new_values.items())
        document.update(new_values)
        return SimpleNamespace(modified_count=int(changed))

    async def insert_one(self, document):
        self.documents.append(document)
        return SimpleNamespace(inserted_id=document["id"])


class MemberSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_syncs_invoking_guild_and_preserves_profile_data(self):
        joined_at = datetime(2024, 1, 2, tzinfo=UTC)
        existing = {
            "id": 7,
            "discord_id": 100,
            "discord_username": "OldDiscordName",
            "dofus_username": "OldDofusName",
            "roles": ["OldRole"],
            "joined_server": joined_at.isoformat(),
            "achievement": [10],
            "presentation": "Keep this",
            "token": "keep-this-token",
        }
        unchanged = {
            "id": 8,
            "discord_id": 101,
            "discord_username": "Unchanged",
            "dofus_username": "SameNick",
            "roles": ["Initiateur"],
            "joined_server": joined_at.isoformat(),
            "achievement": [],
            "token": "another-token",
        }
        users = FakeUsersCollection([existing, unchanged])
        guild = FakeGuild(
            [
                FakeMember(
                    100,
                    "NewDiscordName",
                    "DisplayName",
                    ["Assemblée"],
                    joined_at,
                    nick="ServerNick",
                ),
                FakeMember(
                    101,
                    "Unchanged",
                    "SameNick",
                    ["Initiateur"],
                    joined_at,
                ),
                FakeMember(
                    102,
                    "NewMember",
                    "NewDofusName",
                    ["Initiateur"],
                    joined_at,
                ),
                FakeMember(103, "Bot", "Bot", [], joined_at, bot=True),
            ]
        )

        with patch.object(
            user_registration_service,
            "get_database",
            AsyncMock(return_value={"users": users}),
        ):
            result = await user_registration_service.sync_all_members_to_bdd(guild)

        self.assertEqual(
            result,
            {
                "created": 1,
                "updated": 1,
                "unchanged": 1,
                "skipped": 1,
                "failed": 0,
            },
        )
        self.assertIsNone(guild.requested_limit)
        self.assertEqual(existing["dofus_username"], "ServerNick")
        self.assertEqual(existing["roles"], ["Assemblée"])
        self.assertEqual(existing["achievement"], [10])
        self.assertEqual(existing["presentation"], "Keep this")
        self.assertEqual(existing["token"], "keep-this-token")

        new_user = next(user for user in users.documents if user["discord_id"] == 102)
        self.assertEqual(new_user["dofus_username"], "NewDofusName")
        self.assertEqual(new_user["roles"], ["Initiateur"])
        self.assertEqual(new_user["achievement"], [])
        self.assertTrue(new_user["token"])

    async def test_legacy_user_is_matched_by_discord_username(self):
        joined_at = datetime(2024, 1, 2, tzinfo=UTC)
        legacy_user = {
            "id": 1,
            "discord_username": "LegacyName",
            "dofus_username": "OldName",
            "roles": [],
            "joined_server": joined_at.isoformat(),
            "token": "existing-token",
        }
        users = FakeUsersCollection([legacy_user])
        guild = FakeGuild(
            [
                FakeMember(
                    42,
                    "LegacyName",
                    "CurrentDofusName",
                    ["Conseiller"],
                    joined_at,
                )
            ]
        )

        with patch.object(
            user_registration_service,
            "get_database",
            AsyncMock(return_value={"users": users}),
        ):
            result = await user_registration_service.sync_all_members_to_bdd(guild)

        self.assertEqual(result["updated"], 1)
        self.assertEqual(legacy_user["discord_id"], 42)
        self.assertEqual(legacy_user["dofus_username"], "CurrentDofusName")
        self.assertEqual(legacy_user["token"], "existing-token")


if __name__ == "__main__":
    unittest.main()
