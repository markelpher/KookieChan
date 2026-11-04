"""Testes da cog responsável pelo status do Kookie."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from src.cogs.status import StatusCog
from src.ui.status_messages import (
    STATUS_HISTORY_CLEANUP_INTERVAL_SECONDS,
    STATUS_MESSAGE_HISTORY_SCAN_LIMIT,
)


class StatusCogFlowTest(unittest.IsolatedAsyncioTestCase):
    def make_cog(self, *, online=True):
        state = {
            "online": online,
            "last_http_code": 200 if online else 503,
            "last_response_time": 12,
            "last_check": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "last_status_change": 1234,
            "continuous_online": 60,
            "continuous_offline": 0,
            "total_online": 3600,
            "total_offline": 0,
            "downtimes_count": 0,
            "config": {},
        }
        cog = cast(Any, object.__new__(StatusCog))
        cog.db = object()
        cog.service = SimpleNamespace(
            state=state,
            record_check=AsyncMock(return_value=False),
            set_message_id=AsyncMock(),
            max_gap_seconds=90,
            pending_failures=0,
            failure_confirmations=2,
        )
        cog.bot = SimpleNamespace(get_channel=lambda channel_id: channel)
        cog.pending_status_ping_task = None
        cog._last_status_history_cleanup = 0.0
        message = SimpleNamespace(id=99, pin=AsyncMock())
        channel = SimpleNamespace(send=AsyncMock(return_value=message))
        cog.get_status_message = AsyncMock(return_value=message)
        cog.sync_status_pin = AsyncMock()
        return cog, channel, message

    async def test_load_status_config_updates_panel_state(self):
        cog, _, _ = self.make_cog()
        with patch(
            "src.cogs.status.get_config",
            new=AsyncMock(side_effect=["https://status.example", False]),
        ) as get_config:
            await cog.load_status_config()

        self.assertEqual(get_config.await_count, 2)
        self.assertEqual(
            get_config.await_args_list[0].args, (cog.db, "kookie_status_url")
        )
        self.assertEqual(
            get_config.await_args_list[1].args,
            (cog.db, "status_old_messages_cleanup_enabled", False),
        )
        self.assertEqual(
            cog.state["config"],
            {
                "kookie_status_url": "https://status.example",
                "status_old_messages_cleanup_enabled": False,
            },
        )

    async def test_old_status_cleanup_is_disabled_by_default(self):
        cog, channel, message = self.make_cog()
        channel.history = AsyncMock()

        await cog.cleanup_old_status_messages(channel, message)

        channel.history.assert_not_awaited()

    async def test_old_status_cleanup_deletes_only_prior_bot_status_panels(self):
        cog, channel, _ = self.make_cog()
        cog.bot.user = SimpleNamespace(id=10)
        cog.state["config"]["status_old_messages_cleanup_enabled"] = True
        current = SimpleNamespace(id=99)
        old_status = SimpleNamespace(
            id=98,
            author=SimpleNamespace(id=10),
            components=[
                SimpleNamespace(
                    children=[SimpleNamespace(content="# Status do Kookie")]
                )
            ],
            delete=AsyncMock(),
        )
        other_author = SimpleNamespace(
            id=97,
            author=SimpleNamespace(id=20),
            components=[
                SimpleNamespace(
                    children=[SimpleNamespace(content="# Status do Kookie")]
                )
            ],
            delete=AsyncMock(),
        )
        unrelated = SimpleNamespace(
            id=96,
            author=SimpleNamespace(id=10),
            components=[
                SimpleNamespace(children=[SimpleNamespace(content="# Anúncio")])
            ],
            delete=AsyncMock(),
        )

        history_calls = []

        async def history(**kwargs):
            history_calls.append(kwargs)
            yield current
            yield old_status
            yield other_author
            yield unrelated

        channel.history = history

        with patch("src.ui.status_messages.time.monotonic", side_effect=[1.0, 2.0]):
            await cog.cleanup_old_status_messages(channel, current)
            await cog.cleanup_old_status_messages(channel, current)

        old_status.delete.assert_awaited_once_with()
        other_author.delete.assert_not_awaited()
        unrelated.delete.assert_not_awaited()
        self.assertEqual(history_calls, [{"limit": STATUS_MESSAGE_HISTORY_SCAN_LIMIT}])

    def test_status_history_cleanup_interval_is_fifteen_minutes(self):
        self.assertEqual(STATUS_HISTORY_CLEANUP_INTERVAL_SECONDS, 15 * 60)

    async def test_update_state_edits_existing_message_without_transition(self):
        cog, channel, message = self.make_cog()
        with (
            patch(
                "src.cogs.status.get_config",
                new=AsyncMock(side_effect=[123, "https://status.example", False]),
            ),
            patch("src.cogs.status.edit_panel", new=AsyncMock()) as edit,
        ):
            await cog.update_state(
                {
                    "online": True,
                    "http_code": 200,
                    "timestamp": datetime.now(timezone.utc),
                }
            )

        edit.assert_awaited_once()
        cog.sync_status_pin.assert_awaited_once_with(channel, message)
        cog.service.set_message_id.assert_not_awaited()

    async def test_update_state_sends_and_persists_missing_status_message(self):
        cog, channel, message = self.make_cog()
        cog.get_status_message.return_value = None
        with patch(
            "src.cogs.status.get_config",
            new=AsyncMock(side_effect=[123, "https://status.example", False]),
        ):
            await cog.update_state({"online": True, "http_code": 200})

        channel.send.assert_awaited_once()
        cog.service.set_message_id.assert_awaited_once_with(message.id)
        cog.sync_status_pin.assert_awaited_once_with(channel, message)

    async def test_update_state_schedules_ping_only_after_confirmed_transition(self):
        cog, channel, message = self.make_cog(online=False)
        cog.service.record_check.return_value = True
        scheduled = []

        def capture_task(bot, coroutine, **kwargs):
            scheduled.append((coroutine, kwargs))
            coroutine.close()
            return object()

        with (
            patch(
                "src.cogs.status.get_config",
                new=AsyncMock(
                    side_effect=[123, "https://status.example", False, True, 456]
                ),
            ),
            patch("src.cogs.status.edit_panel", new=AsyncMock()),
            patch("src.cogs.status.supervise_task", side_effect=capture_task),
        ):
            await cog.update_state({"online": False, "http_code": 503})

        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0][1]["owner"], "status")
        self.assertEqual(scheduled[0][1]["name"], "status-change-ping")

    async def test_update_state_returns_when_service_rejects_check(self):
        cog, _, _ = self.make_cog()
        cog.service.record_check.return_value = None
        with patch("src.cogs.status.get_config", new=AsyncMock()) as get_config:
            await cog.update_state({"online": True})
        get_config.assert_not_awaited()

    async def test_status_ping_is_discarded_if_transition_is_stale(self):
        cog, channel, message = self.make_cog(online=False)
        with patch("src.cogs.status.asyncio.sleep", new=AsyncMock()):
            await cog.send_status_ping_notification(
                channel, message, 456, True, 1234, validation_delay=0
            )
        channel.send.assert_not_awaited()

    async def test_status_ping_is_discarded_when_monitoring_is_disabled(self):
        cog, channel, message = self.make_cog(online=True)
        with (
            patch("src.cogs.status.asyncio.sleep", new=AsyncMock()),
            patch("src.cogs.status.get_config", new=AsyncMock(return_value=False)),
        ):
            await cog.send_status_ping_notification(
                channel, message, 456, True, 1234, validation_delay=0
            )

        channel.send.assert_not_awaited()

    async def test_status_ping_sends_deletes_and_refreshes_when_still_current(self):
        cog, channel, message = self.make_cog(online=True)
        sent = SimpleNamespace(delete=AsyncMock())
        channel.send = AsyncMock(return_value=sent)
        channel.fetch_message = AsyncMock(return_value=message)
        with (
            patch("src.cogs.status.asyncio.sleep", new=AsyncMock()),
            patch("src.cogs.status.get_config", new=AsyncMock(return_value=True)),
            patch("src.cogs.status.edit_panel", new=AsyncMock()) as edit,
        ):
            await cog.send_status_ping_notification(
                channel,
                message,
                456,
                True,
                1234,
                validation_delay=0,
                delete_delay=0,
            )

        channel.send.assert_awaited_once()
        sent.delete.assert_awaited_once()
        channel.fetch_message.assert_awaited_once_with(message.id)
        edit.assert_awaited_once()
        cog.sync_status_pin.assert_awaited_once_with(channel, message)

    async def test_status_ping_refresh_uses_cached_message_if_refetch_fails(self):
        cog, channel, message = self.make_cog(online=True)
        channel.fetch_message = AsyncMock(side_effect=RuntimeError("offline"))
        with (
            patch("src.cogs.status.panel", return_value="panel"),
            patch("src.cogs.status.edit_panel", new=AsyncMock()) as edit,
        ):
            await cog.refresh_status_ping_panel(channel, message, 456, None)

        edit.assert_awaited_once_with(message, "panel")
        cog.sync_status_pin.assert_awaited_once_with(channel, message)

    async def test_status_command_sends_private_panel(self):
        cog, _, _ = self.make_cog()
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        with patch(
            "src.cogs.status.get_config",
            new=AsyncMock(return_value="https://status.example"),
        ):
            await cast(Any, StatusCog.status_cmd.callback)(cog, interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.followup.send.assert_awaited_once()
        self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])

    async def test_status_panel_counts_since_current_start_between_checks(self):
        cog, _, _ = self.make_cog()
        now = datetime(2026, 1, 1, 1, 1, 40, tzinfo=timezone.utc)
        cog.state["last_status_change"] = now.timestamp() - 3700
        cog.state["last_check"] = now.replace(second=30)
        cog.state["continuous_online"] = 0

        content = cog.build_status_content(cog.state, current_time=now)

        duration = dict(content.sections)["Tempo contínuo online"]
        self.assertEqual(duration, "1h 01m")

    async def test_status_panel_does_not_count_unadjusted_stale_gap(self):
        cog, _, _ = self.make_cog()
        now = datetime(2026, 1, 1, 1, 1, 40, tzinfo=timezone.utc)
        cog.state["last_status_change"] = now.timestamp() - 3700
        cog.state["last_check"] = now.replace(minute=0, second=0)
        cog.state["continuous_online"] = 60

        content = cog.build_status_content(cog.state, current_time=now)

        duration = dict(content.sections)["Tempo contínuo online"]
        self.assertEqual(duration, "1m")

    async def test_get_status_message_reuses_valid_existing_message(self):
        cog, channel, message = self.make_cog()
        del cog.get_status_message
        cog.bot.user = SimpleNamespace(id=10)
        message.author = SimpleNamespace(id=10)
        message.components = [
            SimpleNamespace(children=[SimpleNamespace(content="# Status do Kookie")])
        ]
        cog.state["status_message_id"] = message.id
        channel.fetch_message = AsyncMock(return_value=message)

        result = await cog.get_status_message(123)

        self.assertIs(result, message)
        channel.fetch_message.assert_awaited_once_with(message.id)

    async def test_get_status_message_recovers_matching_message_from_history(self):
        cog, channel, _ = self.make_cog()
        del cog.get_status_message
        cog.bot.user = SimpleNamespace(id=10)
        cog.state["status_message_id"] = 1
        channel.fetch_message = AsyncMock(side_effect=RuntimeError())
        channel.pins = AsyncMock(return_value=[])
        recovered = SimpleNamespace(
            id=22,
            author=SimpleNamespace(id=10),
            components=[
                SimpleNamespace(
                    children=[SimpleNamespace(content="# Status do Kookie")]
                )
            ],
        )

        history_calls = []

        async def history(**kwargs):
            history_calls.append(kwargs)
            yield recovered

        channel.history = history

        result = await cog.get_status_message(123)

        self.assertIs(result, recovered)
        cog.service.set_message_id.assert_awaited_once_with(recovered.id)
        self.assertEqual(history_calls, [{"limit": STATUS_MESSAGE_HISTORY_SCAN_LIMIT}])

    async def test_get_status_message_recovers_matching_pinned_status_first(self):
        cog, channel, _ = self.make_cog()
        del cog.get_status_message
        cog.bot.user = SimpleNamespace(id=10)
        pinned = SimpleNamespace(
            id=22,
            author=SimpleNamespace(id=10),
            components=[
                SimpleNamespace(
                    children=[SimpleNamespace(content="# Status do Kookie")]
                )
            ],
        )
        channel.pins = AsyncMock(return_value=[pinned])
        channel.history = AsyncMock()

        result = await cog.get_status_message(123)

        self.assertIs(result, pinned)
        channel.history.assert_not_awaited()
        cog.service.set_message_id.assert_awaited_once_with(pinned.id)

    async def test_get_status_message_returns_none_when_history_scan_fails(self):
        cog, channel, _ = self.make_cog()
        del cog.get_status_message
        cog.bot.user = SimpleNamespace(id=10)
        cog.state["status_message_id"] = 1
        channel.fetch_message = AsyncMock(side_effect=RuntimeError("private"))
        channel.pins = AsyncMock(return_value=[])

        async def history(**kwargs):
            raise RuntimeError("private")
            yield None

        channel.history = history
        with self.assertLogs("src.cogs.status", level="WARNING") as logs:
            result = await cog.get_status_message(123)

        self.assertIsNone(result)
        self.assertNotIn("private", logs.output[0])

    async def test_get_status_message_returns_none_without_channel(self):
        cog, _, _ = self.make_cog()
        del cog.get_status_message
        cog.bot.get_channel = lambda channel_id: None
        self.assertIsNone(await cog.get_status_message(123))

    async def test_sync_status_pin_unpins_old_bot_message_and_pins_new(self):
        cog, channel, message = self.make_cog()
        del cog.sync_status_pin
        cog.bot.user = SimpleNamespace(id=10)
        old = SimpleNamespace(
            id=1,
            author=SimpleNamespace(id=10),
            components=[
                SimpleNamespace(
                    children=[SimpleNamespace(content="# Status do Kookie")]
                )
            ],
            unpin=AsyncMock(),
        )
        channel.pins = AsyncMock(return_value=[old])
        cog.delete_pin_notification = AsyncMock()

        await cog.sync_status_pin(channel, message)

        old.unpin.assert_awaited_once()
        message.pin.assert_awaited_once()
        cog.delete_pin_notification.assert_awaited_once_with(channel, message.id)

    async def test_sync_status_pin_preserves_announcement_from_same_bot(self):
        cog, channel, message = self.make_cog()
        del cog.sync_status_pin
        cog.bot.user = SimpleNamespace(id=10)
        announcement = SimpleNamespace(
            id=1,
            author=SimpleNamespace(id=10),
            components=[
                SimpleNamespace(
                    children=[
                        SimpleNamespace(content="# 📢 Última atualização do Kookie")
                    ]
                )
            ],
            unpin=AsyncMock(),
        )
        channel.pins = AsyncMock(return_value=[announcement])
        cog.delete_pin_notification = AsyncMock()

        await cog.sync_status_pin(channel, message)

        announcement.unpin.assert_not_awaited()
        message.pin.assert_awaited_once()

    async def test_sync_status_pin_compares_ids_before_pinning(self):
        cog, channel, message = self.make_cog()
        del cog.sync_status_pin
        cog.bot.user = SimpleNamespace(id=10)
        current_pin = SimpleNamespace(id=message.id, author=SimpleNamespace(id=10))
        channel.pins = AsyncMock(return_value=[current_pin])
        cog.delete_pin_notification = AsyncMock()

        await cog.sync_status_pin(channel, message)

        message.pin.assert_not_awaited()
        cog.delete_pin_notification.assert_not_awaited()
