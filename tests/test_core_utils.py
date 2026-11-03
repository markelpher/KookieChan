"""Testes das funções utilitárias compartilhadas."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.core.utils import (
    announcement_date,
    discord_timestamp,
    format_datetime_br,
    get_config,
    get_site_status,
    ms_to_str,
    parse_brazilian_date,
    set_config,
)


class CoreUtilsTest(unittest.IsolatedAsyncioTestCase):
    def test_date_helpers_cover_fallbacks_and_invalid_input(self):
        self.assertEqual(parse_brazilian_date("01/02/2026").hour, 0)
        with self.assertRaisesRegex(ValueError, "Formato de data inválido"):
            parse_brazilian_date("invalid")
        self.assertEqual(format_datetime_br("not a datetime"), "not a datetime")
        self.assertIn("<t:", discord_timestamp(datetime(2026, 1, 1)))
        self.assertEqual(
            announcement_date(datetime(2026, 5, 1, tzinfo=timezone.utc)), "30/04/2026"
        )

    def test_elapsed_time_formats_minutes_hours_and_days(self):
        self.assertEqual(ms_to_str(2 * 86400000 + 3660000), "2d 1h 01m")
        self.assertEqual(ms_to_str(65 * 60000), "1h 05m")
        self.assertEqual(ms_to_str(60000), "1m")

    async def test_config_helpers_use_defaults_and_persist(self):
        db = SimpleNamespace(
            get_config=AsyncMock(side_effect=[None, False]), set_config=AsyncMock()
        )
        self.assertEqual(await get_config(db, "absent", "fallback"), "fallback")
        self.assertFalse(await get_config(db, "false", True))
        await set_config(db, "key", 123)
        db.set_config.assert_awaited_once_with("key", 123)

    async def test_site_status_returns_http_result(self):
        response = SimpleNamespace(status=204)

        class ResponseContext:
            async def __aenter__(self):
                return response

            async def __aexit__(self, *args):
                return False

        session = SimpleNamespace(get=lambda *args, **kwargs: ResponseContext())
        result = await get_site_status("https://status.example", session=session)
        self.assertTrue(result["online"])
        self.assertEqual(result["http_code"], 204)

    async def test_site_status_converts_request_failure_to_offline_result(self):
        class FailedResponseContext:
            async def __aenter__(self):
                raise TimeoutError()

            async def __aexit__(self, *args):
                return False

        session = SimpleNamespace(get=lambda *args, **kwargs: FailedResponseContext())
        result = await get_site_status("https://status.example", session=session)
        self.assertFalse(result["online"])
        self.assertEqual(result.get("error"), "TimeoutError")

    async def test_site_status_checks_ip_literal_when_creating_shared_session(self):
        with (
            patch(
                "src.core.utils.ensure_public_ip_literal",
                side_effect=ValueError("blocked"),
            ),
            patch("src.core.utils.get_http_session") as get_session,
        ):
            result = await get_site_status("http://127.0.0.1")

        get_session.assert_not_called()
        self.assertEqual(result.get("error"), "ValueError")
