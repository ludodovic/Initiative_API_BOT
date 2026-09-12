import json
import unittest
from io import BytesIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from app.api import main as api
from app.services import user_service
from app.services.user_service import InvalidProfilePicture, parse_birthday


def response_body(response):
    return json.loads(response.body.decode("utf-8"))


class ProfileApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_birthday_update_preserves_omitted_field_and_allows_null(self):
        expected = {
            "birthday": "1990-05-15",
            "wish": None,
            "message": "Birthday information updated",
        }
        with (
            patch.object(api, "get_user_by_token", AsyncMock(return_value={"id": 1})),
            patch.object(api, "update_user_birthday", AsyncMock(return_value=expected)) as update,
        ):
            response = await api.api_user_birthday_update(
                {"wish": None}, "Bearer valid-token"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_body(response), expected)
        update.assert_awaited_once_with("valid-token", wish=None)

    async def test_birthday_rejects_timestamp_instead_of_accepting_iso_datetime(self):
        with patch.object(
            api, "get_user_by_token", AsyncMock(return_value={"id": 1})
        ):
            response = await api.api_user_birthday_update(
                {"birthday": "1990-05-15T12:00:00"}, "Bearer valid-token"
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response_body(response)["error"], "INVALID_DATE")

    async def test_secondary_classes_reject_main_class(self):
        with patch.object(
            api,
            "get_user_by_token",
            AsyncMock(return_value={"id": 1, "class": "Iop"}),
        ):
            response = await api.api_user_classes_update(
                {"secondary_classes": ["Iop", "Eni"]}, "Bearer valid-token"
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response_body(response)["error"], "INVALID_CLASS")

    async def test_invalid_token_is_unauthorized_before_validation(self):
        with patch.object(api, "get_user_by_token", AsyncMock(return_value=None)):
            response = await api.api_user_presentation_update({}, "Bearer invalid")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response_body(response),
            {
                "error": "UNAUTHORIZED",
                "message": "Authentication token required",
                "details": None,
            },
        )


class ProfileValidationTests(unittest.TestCase):
    def test_parse_birthday_accepts_exact_calendar_date(self):
        self.assertEqual(parse_birthday("1990-05-15").isoformat(), "1990-05-15")

    def test_parse_birthday_rejects_datetime(self):
        with self.assertRaises(ValueError):
            parse_birthday("1990-05-15T12:00:00")

    def test_profile_picture_is_stored_at_public_url(self):
        image_bytes = BytesIO()
        Image.new("RGB", (32, 32), "red").save(image_bytes, "JPEG")

        with TemporaryDirectory() as upload_dir, patch.object(
            user_service,
            "get_settings",
            return_value=SimpleNamespace(
                profile_picture_upload_dir=upload_dir, api_public_url=""
            ),
        ):
            picture_url, picture_path = user_service._store_profile_picture(
                7, image_bytes.getvalue(), "image/jpeg"
            )

            self.assertTrue(picture_path.is_file())
            self.assertTrue(picture_url.startswith("/uploads/profile-pictures/user_7/"))

    def test_profile_picture_rejects_mime_content_mismatch(self):
        image_bytes = BytesIO()
        Image.new("RGB", (32, 32), "blue").save(image_bytes, "PNG")

        with TemporaryDirectory() as upload_dir, patch.object(
            user_service,
            "get_settings",
            return_value=SimpleNamespace(
                profile_picture_upload_dir=upload_dir, api_public_url=""
            ),
        ):
            with self.assertRaises(InvalidProfilePicture):
                user_service._store_profile_picture(
                    7, image_bytes.getvalue(), "image/jpeg"
                )


class FakeSuccessCursor:
    def __init__(self, successes):
        self.successes = iter(successes)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.successes)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeSuccessCollection:
    def __init__(self, successes):
        self.successes = successes
        self.find_args = None

    def find(self, *args):
        self.find_args = args
        return FakeSuccessCursor(self.successes)


class FakeUserCollection:
    def __init__(self, user):
        self.user = user
        self.find_one_args = None

    async def find_one(self, *args):
        self.find_one_args = args
        return self.user


class SeasonTwoTicketTests(unittest.IsolatedAsyncioTestCase):
    async def test_total_includes_bonus_ticket_count(self):
        successes = FakeSuccessCollection(
            [
                {"difficulte": "***"},
                {"difficulte": "*"},
                {"difficulte": "**"},
                {"difficulte": "*"},
            ]
        )
        users = FakeUserCollection({"bonus_ticket_count": 6})
        with patch.object(
            user_service,
            "get_database",
            AsyncMock(return_value={"succes2": successes, "users": users}),
        ):
            result = await user_service.get_total_season2_tickets("valid-token")

        self.assertEqual(result, {"total": 13})
        self.assertEqual(
            successes.find_args,
            ({}, {"_id": 0, "difficulte": 1}),
        )
        self.assertEqual(
            users.find_one_args,
            (
                {"token": "valid-token"},
                {"_id": 0, "bonus_ticket_count": 1},
            ),
        )


if __name__ == "__main__":
    unittest.main()
