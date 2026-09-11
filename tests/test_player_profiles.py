import json
import unittest
from unittest.mock import AsyncMock, patch

from app.api import main as api
from app.services import user_service


def response_body(response):
    return json.loads(response.body.decode("utf-8"))


class FakeCursor:
    def __init__(self, documents):
        self.documents = iter(documents)
        self.sort_args = None

    def sort(self, *args):
        self.sort_args = args
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.documents)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeUsersCollection:
    def __init__(self, documents):
        self.cursor = FakeCursor(documents)
        self.find_args = None

    def find(self, *args):
        self.find_args = args
        return self.cursor


class PlayerProfileApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_requires_authentication(self):
        with patch.object(api, "get_user_by_token", AsyncMock(return_value=None)):
            response = await api.api_profiles(None)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response_body(response)["error"], "UNAUTHORIZED")

    async def test_list_forbids_user_without_current_guild_role(self):
        with patch.object(
            api, "get_user_by_token", AsyncMock(return_value={"roles": []})
        ):
            response = await api.api_profiles("Bearer valid-token")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response_body(response)["error"], "FORBIDDEN")

    async def test_one_profile_url_decodes_username_before_exact_lookup(self):
        expected = {
            "dofus_username": "Player Name",
            "class": None,
            "profile_picture_url": None,
            "birthday": None,
            "wish": None,
            "presentation": None,
            "secondary_classes": [],
            "roles": [],
        }
        with (
            patch.object(
                api,
                "get_user_by_token",
                AsyncMock(return_value={"roles": ["Initiateur"]}),
            ),
            patch.object(
                api, "get_player_profile", AsyncMock(return_value=expected)
            ) as lookup,
        ):
            response = await api.api_player_profile(
                "Player%20Name", "Bearer valid-token"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_body(response), expected)
        lookup.assert_awaited_once_with("Player Name")

    async def test_one_profile_returns_contract_404(self):
        with (
            patch.object(
                api,
                "get_user_by_token",
                AsyncMock(return_value={"roles": ["Assemblée"]}),
            ),
            patch.object(api, "get_player_profile", AsyncMock(return_value=None)),
        ):
            response = await api.api_player_profile(
                "Unknown", "Bearer valid-token"
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response_body(response),
            {
                "error": "PROFILE_NOT_FOUND",
                "message": "Player profile not found",
                "details": None,
            },
        )


class PlayerProfileFormattingTests(unittest.TestCase):
    def test_formatter_exposes_only_public_fields_and_recognized_roles(self):
        user = {
            "id": 12,
            "token": "secret",
            "discord_id": 42,
            "email": "private@example.com",
            "dofus_username": "PlayerName",
            "class": "Iop",
            "profile_picture_url": None,
            "birthday": "2000-05-15",
            "birthday_wish": "Un message",
            "presentation": "Ma présentation",
            "secondary_classes": None,
            "roles": ["Conseiller", "Unrelated", "Initiateur"],
        }

        result = user_service._format_public_profile(user)

        self.assertEqual(result["secondary_classes"], [])
        self.assertEqual(result["roles"], ["Initiateur", "Conseiller"])
        self.assertNotIn("token", result)
        self.assertNotIn("discord_id", result)
        self.assertNotIn("email", result)

    def test_view_permission_requires_recognized_current_role(self):
        self.assertTrue(
            user_service.can_view_player_profiles({"roles": ["Assemblée"]})
        )
        self.assertFalse(
            user_service.can_view_player_profiles({"roles": ["Unrelated"]})
        )


class PlayerProfileServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_queries_only_nonblank_presentations_and_classes(self):
        users = FakeUsersCollection([])
        with patch.object(
            user_service,
            "get_database",
            AsyncMock(return_value={"users": users}),
        ):
            result = await user_service.list_displayable_profiles()

        self.assertEqual(result, [])
        query, projection = users.find_args
        self.assertEqual(query["presentation"], {"$type": "string", "$regex": r"\S"})
        self.assertEqual(query["class"], {"$type": "string", "$regex": r"\S"})
        self.assertEqual(projection, user_service.PUBLIC_PROFILE_PROJECTION)
        self.assertEqual(users.cursor.sort_args, ("dofus_username", 1))


if __name__ == "__main__":
    unittest.main()
