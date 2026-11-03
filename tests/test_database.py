"""Testes do cliente e das operações de persistência."""

import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web

import src.database.database as database_module
from src.database.announcement_repository import AnnouncementRepository
from src.database.database import Database


class DatabaseAPITest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []

        async def handle(request):
            body = await request.json() if request.can_read_body else None
            self.requests.append((request.path, dict(request.headers), body))
            if request.path.endswith("/rpc/record_status_check"):
                return web.Response(status=204)
            if request.path.endswith("/error"):
                return web.json_response(
                    {"code": "42501", "message": "sb_secret_confidencial"}, status=403
                )
            return web.json_response([{"value": 42}])

        app = web.Application()
        app.router.add_route("*", "/rest/v1/{path:.*}", handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        server = cast(asyncio.Server | None, site._server)
        self.assertIsNotNone(server)
        assert server is not None
        port = server.sockets[0].getsockname()[1]
        self.db = Database(f"http://127.0.0.1:{port}", "sb_secret_test")

    async def asyncTearDown(self):
        await self.db.session.close()
        await self.runner.cleanup()

    async def test_secret_key_and_config(self):
        self.assertEqual(await self.db.get_config("example"), 42)
        self.assertEqual(self.requests[0][1]["apikey"], "sb_secret_test")
        self.assertNotIn("Authorization", self.requests[0][1])

    async def test_get_configs_fetches_all_settings_in_one_request(self):
        calls = []

        async def request(method, path, *, params=None, **kwargs):
            calls.append((method, path, params))
            return [{"key": "status_channel_id", "value": 123}]

        self.db.request = request
        values = await self.db.get_configs(
            ("status_channel_id", "status_monitor_enabled")
        )
        self.assertEqual(values, {"status_channel_id": 123})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "bot_config")
        self.assertEqual(calls[0][2]["select"], "key,value")
        self.assertEqual(
            calls[0][2]["key"], "in.(status_channel_id,status_monitor_enabled)"
        )

    async def test_get_configs_returns_empty_mapping_for_empty_response(self):
        self.db.request = AsyncMock(return_value=None)

        self.assertEqual(await self.db.get_configs(("status_channel_id",)), {})

    async def test_status_history_query_uses_requested_limit(self):
        self.db.request = AsyncMock(return_value=[])

        await self.db.list_status(17)

        self.db.request.assert_awaited_once_with(
            "GET",
            "status_logs",
            params={"select": "*", "order": "checked_at.desc", "limit": "17"},
        )

    async def test_announcement_history_query_uses_requested_limit(self):
        self.db.request = AsyncMock(return_value=[])
        repository = AnnouncementRepository(self.db)

        await repository.list_updates(17)

        self.db.request.assert_awaited_once_with(
            "GET",
            "updates",
            params={"select": "*", "order": "timestamp.desc", "limit": "17"},
        )

    async def test_set_configs_saves_urls_in_one_upsert(self):
        await self.db.set_configs(
            {
                "kookie_status_url": "https://kookie.app",
                "kookie_update_url": "https://kookie.app/announcements",
            }
        )
        path, _, payload = self.requests[0]
        self.assertEqual(path, "/rest/v1/bot_config")
        self.assertEqual(
            payload,
            [
                {"key": "kookie_status_url", "value": "https://kookie.app"},
                {
                    "key": "kookie_update_url",
                    "value": "https://kookie.app/announcements",
                },
            ],
        )

    async def test_database_errors_do_not_expose_response_body(self):
        with self.assertRaises(RuntimeError) as error:
            await self.db.request("GET", "error")
        self.assertIn("42501", str(error.exception))
        self.assertNotIn("sb_secret_confidencial", str(error.exception))

    async def test_connection_error_does_not_expose_url_or_credentials(self):
        self.db._request = AsyncMock(
            side_effect=aiohttp.ClientError("https://service/?token=secret")
        )
        with self.assertRaises(RuntimeError) as error:
            await self.db.request("GET", "updates")
        self.assertNotIn("secret", str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)

    async def test_record_check_uses_atomic_rpc(self):
        await self.db.record_check(
            {"online": True},
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "online": True,
                "http_code": 200,
                "response_time": 10,
            },
        )
        self.assertEqual(self.requests[0][0], "/rest/v1/rpc/record_status_check")
        self.assertTrue(self.requests[0][2]["p_state"]["online"])
        self.assertNotIn("state", self.requests[0][2]["p_state"])

    async def test_save_state_uses_typed_columns(self):
        await self.db.save_state(
            {
                "online": True,
                "last_status_change": 100,
                "last_check_ts": 160,
                "last_check": datetime.fromtimestamp(160, timezone.utc),
                "total_online": 60,
                "config": {"temporary": True},
            }
        )
        payload = self.requests[0][2]
        self.assertEqual(payload["status_started_at"], "1970-01-01T00:01:40+00:00")
        self.assertEqual(payload["accounting_at"], "1970-01-01T00:02:40+00:00")
        self.assertEqual(payload["total_online"], 60)
        self.assertFalse(payload["manual_status_start"])
        self.assertNotIn("state", payload)
        self.assertNotIn("config", payload)

    async def test_state_round_trip(self):
        row = {
            "id": "kookie",
            "online": False,
            "status_started_at": "2026-01-01T00:00:00+00:00",
            "accounting_at": "2026-01-01T00:01:00Z",
            "last_check_at": "2026-01-01T00:01:00Z",
            "total_offline": 60,
            "manual_status_start": True,
        }

        async def request(*args, **kwargs):
            return [row]

        self.db.request = request
        state = await self.db.get_state()
        self.assertIsNotNone(state)
        assert state is not None
        assert state["last_check_ts"] is not None
        assert state["last_status_change"] is not None
        assert state["last_check"] is not None
        self.assertEqual(state["last_check_ts"] - state["last_status_change"], 60)
        self.assertEqual(state["last_check"].tzinfo, timezone.utc)
        self.assertTrue(state["manual_status_start"])
        self.assertEqual(self.db.state_columns(state)["total_offline"], 60)

    async def test_delivery_updates_are_conditional(self):
        calls = []

        async def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return [{"id": 42}]

        self.db.request = request
        repository = AnnouncementRepository(self.db)
        await repository.start_update_delivery(42, 123, "2026-01-01T00:00:00+00:00")
        await repository.mark_update_sent(42, 999, "2026-01-01T00:01:00+00:00")
        self.assertEqual(calls[0][2]["params"]["delivery_attempted_at"], "is.null")
        self.assertEqual(calls[0][2]["data"]["delivery_channel_id"], 123)
        self.assertEqual(calls[1][2]["params"]["delivery_status"], "eq.pending")
        self.assertEqual(calls[1][2]["data"]["delivery_status"], "sent")


class DatabaseInitializationTest(unittest.IsolatedAsyncioTestCase):
    async def test_supabase_probe_failure_closes_session_and_clears_global_client(self):
        database = SimpleNamespace(
            request=AsyncMock(side_effect=RuntimeError("probe failed")),
            session=SimpleNamespace(close=AsyncMock()),
        )
        previous_database = database_module._db
        try:
            with (
                patch(
                    "src.database.database.os.getenv",
                    side_effect=lambda key: {
                        "SUPABASE_URL": "https://supabase.example",
                        "SUPABASE_SECRET_KEY": "test-secret",
                    }.get(key),
                ),
                patch("src.database.database.Database", return_value=database),
            ):
                database_module._db = None
                with self.assertRaisesRegex(RuntimeError, "probe failed"):
                    await database_module.init_database()

            database.request.assert_awaited_once_with(
                "GET", "bot_config", params={"select": "key", "limit": "1"}
            )
            database.session.close.assert_awaited_once_with()
            self.assertIsNone(database_module._db)
        finally:
            database_module._db = previous_database
