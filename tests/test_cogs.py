"""Testes das cogs e de seus comandos do Discord."""

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from src.cogs.ping import PingCog
from src.cogs.status import StatusCog
from src.cogs.update import UpdateCog
from src.core.background import cancel_supervised_tasks, supervise_task


class PingCogTest(unittest.IsolatedAsyncioTestCase):
    async def test_ping_sends_ephemeral_panel_with_latency(self):
        cog = PingCog(SimpleNamespace(latency=0.075))
        interaction = SimpleNamespace(
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        await cast(Any, PingCog.ping.callback)(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )
        view = interaction.response.send_message.await_args.kwargs["view"]
        self.assertIn("75 ms", str(view.to_components()))


class StatusCogTest(unittest.IsolatedAsyncioTestCase):
    def make_cog(self):
        cog = cast(Any, object.__new__(StatusCog))
        cog.db = object()
        cog.update_state = AsyncMock()
        return cog

    async def test_monitor_skips_http_when_disabled(self):
        cog = self.make_cog()
        with (
            patch("src.cogs.status.get_config", new=AsyncMock(return_value=False)),
            patch("src.cogs.status.get_site_status", new=AsyncMock()) as fetch,
        ):
            await StatusCog.monitor.coro(cog)

        fetch.assert_not_awaited()
        cog.update_state.assert_not_awaited()

    async def test_monitor_discards_result_if_disabled_during_request(self):
        cog = self.make_cog()
        check = {"online": True, "http_code": 200, "response_time": 10}
        with (
            patch(
                "src.cogs.status.get_config",
                new=AsyncMock(side_effect=[True, "https://status.example", False]),
            ),
            patch(
                "src.cogs.status.get_site_status", new=AsyncMock(return_value=check)
            ) as fetch,
        ):
            await StatusCog.monitor.coro(cog)

        fetch.assert_awaited_once_with("https://status.example")
        cog.update_state.assert_not_awaited()


class UpdateCogTest(unittest.IsolatedAsyncioTestCase):
    def make_cog(self, channel):
        cog = cast(Any, object.__new__(UpdateCog))
        cog.db = object()
        cog.bot = SimpleNamespace(get_channel=lambda channel_id: channel)
        cog.service = SimpleNamespace(run_cycle=AsyncMock())
        return cog

    async def test_cycle_skips_fetch_without_configured_channel(self):
        cog = self.make_cog(None)
        with patch(
            "src.cogs.update.get_config", new=AsyncMock(side_effect=[True, 123])
        ):
            await UpdateCog.auto_post_update.coro(cog)

        cog.service.run_cycle.assert_not_awaited()

    async def test_cycle_runs_for_configured_channel_and_url(self):
        channel = SimpleNamespace(id=123)
        cog = self.make_cog(channel)
        with patch(
            "src.cogs.update.get_config",
            new=AsyncMock(side_effect=[True, 123, "https://news.example"]),
        ):
            await UpdateCog.auto_post_update.coro(cog)

        cog.service.run_cycle.assert_awaited_once_with("https://news.example", channel)

    async def test_cycle_processes_pending_updates_when_url_cannot_be_loaded(self):
        channel = SimpleNamespace(id=123)
        cog = self.make_cog(channel)
        with (
            patch(
                "src.cogs.update.get_config",
                new=AsyncMock(
                    side_effect=[True, 123, RuntimeError("sensitive configuration")]
                ),
            ),
            self.assertLogs("src.cogs.update", level="WARNING") as captured,
        ):
            await UpdateCog.auto_post_update.coro(cog)

        cog.service.run_cycle.assert_awaited_once_with(None, channel)
        self.assertNotIn("sensitive configuration", captured.output[0])

    async def test_cycle_logs_failure_without_exposing_exception_text(self):
        channel = SimpleNamespace(id=123)
        cog = self.make_cog(channel)
        cog.service.run_cycle.side_effect = RuntimeError("sensitive response body")
        with (
            patch(
                "src.cogs.update.get_config",
                new=AsyncMock(side_effect=[True, 123, "https://news.example"]),
            ),
            self.assertLogs("src.cogs.update", level="ERROR") as captured,
        ):
            await UpdateCog.auto_post_update.coro(cog)

        self.assertIn("canal id=123", captured.output[0])
        self.assertNotIn("sensitive response body", captured.output[0])


class BackgroundTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_by_owner_does_not_cancel_other_cog_tasks(self):
        bot = SimpleNamespace()
        started = asyncio.Event()

        async def wait_forever():
            started.set()
            await asyncio.Event().wait()

        status_task = supervise_task(
            bot, wait_forever(), name="status-test", owner="status"
        )
        config_task = supervise_task(
            bot, wait_forever(), name="config-test", owner="config"
        )
        await started.wait()

        await cancel_supervised_tasks(bot, owner="status")

        self.assertIsNotNone(status_task)
        self.assertIsNotNone(config_task)
        assert status_task is not None and config_task is not None
        self.assertTrue(status_task.cancelled())
        self.assertFalse(config_task.cancelled())
        await cancel_supervised_tasks(bot)
        assert config_task is not None
        self.assertTrue(config_task.cancelled())
