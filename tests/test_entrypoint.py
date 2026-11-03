"""Testes do carregamento de extensões na inicialização."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import src.main as main_module
from src.main import load_cogs


class EntrypointTest(unittest.IsolatedAsyncioTestCase):
    async def test_cogs_are_discovered_independently_of_working_directory(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch("src.main.load_cog", new_callable=AsyncMock) as load:
                    await load_cogs()
                names = {call.args[0] for call in load.await_args_list}
                self.assertEqual(
                    names,
                    {
                        f"src.cogs.{name}"
                        for name in (
                            "config",
                            "help",
                            "history",
                            "ping",
                            "presence",
                            "status",
                            "update",
                        )
                    },
                )
            finally:
                os.chdir(original)

    async def test_main_closes_resources_when_cog_loading_fails(self):
        fake_bot = SimpleNamespace(
            is_closed=Mock(return_value=False),
            close=AsyncMock(),
            start=AsyncMock(),
        )
        with (
            patch("src.main.bot", fake_bot),
            patch("src.main.init_database", new=AsyncMock()),
            patch(
                "src.main.load_cogs",
                new=AsyncMock(side_effect=RuntimeError("extension failed")),
            ),
            patch("src.main.cancel_supervised_tasks", new=AsyncMock()) as cancel,
            patch("src.main.close_http_session", new=AsyncMock()) as close_http,
            patch("src.main.close_database", new=AsyncMock()) as close_db,
        ):
            with self.assertRaisesRegex(RuntimeError, "extension failed"):
                await main_module.main()

        fake_bot.start.assert_not_awaited()
        fake_bot.close.assert_awaited_once_with()
        cancel.assert_awaited_once_with(fake_bot)
        close_http.assert_awaited_once_with()
        close_db.assert_awaited_once_with()

    async def test_main_closes_resources_when_discord_start_fails(self):
        fake_bot = SimpleNamespace(
            is_closed=Mock(return_value=False),
            close=AsyncMock(),
            start=AsyncMock(side_effect=RuntimeError("discord unavailable")),
        )
        with (
            patch("src.main.bot", fake_bot),
            patch("src.main.init_database", new=AsyncMock()),
            patch("src.main.load_cogs", new=AsyncMock()),
            patch("src.main.os.getenv", return_value="test-token"),
            patch("src.main.cancel_supervised_tasks", new=AsyncMock()) as cancel,
            patch("src.main.close_http_session", new=AsyncMock()) as close_http,
            patch("src.main.close_database", new=AsyncMock()) as close_db,
        ):
            with self.assertRaisesRegex(RuntimeError, "discord unavailable"):
                await main_module.main()

        fake_bot.start.assert_awaited_once_with("test-token")
        fake_bot.close.assert_awaited_once_with()
        cancel.assert_awaited_once_with(fake_bot)
        close_http.assert_awaited_once_with()
        close_db.assert_awaited_once_with()

    async def test_main_without_token_still_closes_initialized_resources(self):
        fake_bot = SimpleNamespace(
            is_closed=Mock(return_value=False),
            close=AsyncMock(),
            start=AsyncMock(),
        )
        with (
            patch("src.main.bot", fake_bot),
            patch("src.main.init_database", new=AsyncMock()),
            patch("src.main.load_cogs", new=AsyncMock()),
            patch("src.main.os.getenv", return_value=None),
            patch("src.main.cancel_supervised_tasks", new=AsyncMock()) as cancel,
            patch("src.main.close_http_session", new=AsyncMock()) as close_http,
            patch("src.main.close_database", new=AsyncMock()) as close_db,
        ):
            with self.assertRaisesRegex(RuntimeError, "DISCORD_TOKEN"):
                await main_module.main()

        fake_bot.start.assert_not_awaited()
        fake_bot.close.assert_awaited_once_with()
        cancel.assert_awaited_once_with(fake_bot)
        close_http.assert_awaited_once_with()
        close_db.assert_awaited_once_with()
