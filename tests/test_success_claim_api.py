import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from app.api import main as api


class SuccessClaimMultipartTests(unittest.TestCase):
    @staticmethod
    def _post_claim(*, files=None, season=1):
        success = {"id": 42, "name": "Test success"}
        find_success_result = success if season == 1 else None
        season2_collection = SimpleNamespace(
            find_one=AsyncMock(return_value=success if season == 2 else None)
        )
        create_claim = AsyncMock(return_value={"claimId": "claim-42"})

        with (
            patch.object(
                api,
                "get_user_by_token",
                AsyncMock(return_value={"id": 7, "dofus_username": "Player"}),
            ),
            patch.object(
                api, "find_success", AsyncMock(return_value=find_success_result)
            ),
            patch.object(
                api,
                "get_database",
                AsyncMock(return_value={"succes2": season2_collection}),
            ),
            patch.object(api, "create_success_claim", create_claim),
            patch.object(api, "get_bot", Mock(return_value=object())),
            patch.object(
                api, "post_success_claim_for_validation", AsyncMock()
            ) as post_to_discord,
            TestClient(api.app) as client,
        ):
            response = client.post(
                "/api/succes/claim",
                headers={"Authorization": "Bearer valid-token"},
                data={
                    "successId": "42",
                    "successName": "Test success",
                    "successDescription": "Complete the test",
                    "description": "Regression test",
                },
                files=files,
            )

        return response, create_claim, post_to_discord

    def test_season1_accepts_one_png_without_validation_error(self):
        response, create_claim, post_to_discord = self._post_claim(
            files=[("images", ("proof.png", b"png-one", "image/png"))]
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"ok": True, "claimId": "claim-42"})
        self.assertEqual(
            create_claim.await_args.kwargs["images"],
            [("image/png", b"png-one")],
        )
        post_to_discord.assert_awaited_once()

    def test_season1_receives_repeated_image_fields_and_processes_three(self):
        files = [
            ("images", (f"proof-{index}.png", f"png-{index}".encode(), "image/png"))
            for index in range(1, 5)
        ]

        response, create_claim, _ = self._post_claim(files=files)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            create_claim.await_args.kwargs["images"],
            [
                ("image/png", b"png-1"),
                ("image/png", b"png-2"),
                ("image/png", b"png-3"),
            ],
        )

    def test_season1_requires_at_least_one_image(self):
        response, create_claim, post_to_discord = self._post_claim()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "At least one image is required")
        create_claim.assert_not_awaited()
        post_to_discord.assert_not_awaited()

    def test_season2_accepts_claim_without_an_image(self):
        response, create_claim, post_to_discord = self._post_claim(season=2)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(create_claim.await_args.kwargs["images"], [])
        post_to_discord.assert_awaited_once()

    def test_invalid_image_mime_type_returns_bad_request(self):
        response, create_claim, post_to_discord = self._post_claim(
            files=[("images", ("proof.txt", b"not-an-image", "text/plain"))]
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["message"], "Only PNG and JPG images are accepted"
        )
        create_claim.assert_not_awaited()
        post_to_discord.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
