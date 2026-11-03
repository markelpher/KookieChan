"""Testes da presença e das atividades do bot."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import discord

from src.cogs.presence import PRESENCE_ROTATION, PresenceCog


class PresenceCogTest(unittest.IsolatedAsyncioTestCase):
    def make_cog(self):
        bot = SimpleNamespace(
            change_presence=AsyncMock(),
            wait_until_ready=AsyncMock(),
            get_cog=Mock(return_value=None),
        )
        return PresenceCog(bot), bot

    def test_downtime_text_uses_confirmed_offline_duration(self):
        now = datetime(2026, 5, 1, 2, 3, 12, tzinfo=timezone.utc)
        started = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc).timestamp()
        status_cog = SimpleNamespace(
            state={
                "online": False,
                "last_status_change": started,
            }
        )
        cog, bot = self.make_cog()
        bot.get_cog.return_value = status_cog

        self.assertEqual(
            cog.downtime_status(now=now),
            "👻 Já faz 2h que o Kookie está fora do ar",
        )

    def test_downtime_text_shows_only_the_largest_unit(self):
        now = datetime(2026, 5, 2, tzinfo=timezone.utc)
        cog, bot = self.make_cog()
        for elapsed, expected in (
            (59 * 60 + 59, "59m"),
            (60 * 60, "1h"),
            (2 * 86400 + 23 * 3600, "2d"),
        ):
            bot.get_cog.return_value = SimpleNamespace(
                state={
                    "online": False,
                    "last_status_change": now.timestamp() - elapsed,
                }
            )
            self.assertEqual(
                cog.downtime_status(now=now),
                f"👻 Já faz {expected} que o Kookie está fora do ar",
            )

    def test_downtime_text_is_absent_when_status_is_online_unknown_or_unstarted(self):
        cog, bot = self.make_cog()
        for state in (
            {"online": True, "last_status_change": 100},
            {"online": None, "last_status_change": 100},
            {"online": False, "last_status_change": None},
        ):
            bot.get_cog.return_value = SimpleNamespace(state=state)
            self.assertIsNone(cog.downtime_status())

    async def test_confirmed_downtime_overrides_rotation_and_updates_custom_status(
        self,
    ):
        cog, bot = self.make_cog()
        now = datetime.now(timezone.utc)
        bot.get_cog.return_value = SimpleNamespace(
            state={
                "online": False,
                "last_status_change": now.timestamp() - 125,
            }
        )

        await PresenceCog.rotate_presence.coro(cog)

        activity = bot.change_presence.await_args.kwargs["activity"]
        self.assertIsInstance(activity, discord.CustomActivity)
        self.assertEqual(activity.name, "👻 Já faz 2m que o Kookie está fora do ar")
        self.assertIsNone(activity.emoji)
        self.assertEqual(cog.activity_index, 0)

    async def test_rotates_through_activities_and_wraps_around(self):
        cog, bot = self.make_cog()

        for index in range(len(PRESENCE_ROTATION) + 1):
            await PresenceCog.rotate_presence.coro(cog)
            activity = bot.change_presence.await_args.kwargs["activity"]
            expected_type, expected_name = PRESENCE_ROTATION[
                index % len(PRESENCE_ROTATION)
            ]
            self.assertEqual(activity.type, expected_type)
            self.assertEqual(activity.name, expected_name)
            if expected_type is discord.ActivityType.custom:
                self.assertIsInstance(activity, discord.CustomActivity)
                self.assertEqual(str(activity.emoji), "👻")
                self.assertEqual(activity.to_dict()["state"], expected_name)
            else:
                self.assertIsInstance(activity, discord.Activity)

        self.assertEqual(cog.activity_index, 1)
        self.assertEqual(bot.change_presence.await_count, len(PRESENCE_ROTATION) + 1)

    def test_rotation_mentions_kookie_and_cookies(self):
        all_text = " ".join(text for _, text in PRESENCE_ROTATION).casefold()
        self.assertIn("kookie", all_text)
        self.assertIn("cookie", all_text)
        self.assertTrue(
            all(
                activity_type is discord.ActivityType.custom
                for activity_type, _ in PRESENCE_ROTATION
            )
        )

    async def test_failed_presence_update_keeps_current_activity_for_retry(self):
        cog, bot = self.make_cog()
        bot.change_presence.side_effect = discord.HTTPException(
            cast(Any, SimpleNamespace(status=500, reason="error")),
            "unavailable",
        )

        with self.assertLogs("src.cogs.presence", level="WARNING"):
            await PresenceCog.rotate_presence.coro(cog)

        self.assertEqual(cog.activity_index, 0)

    async def test_on_ready_starts_loop_only_once(self):
        cog, _ = self.make_cog()
        loop = SimpleNamespace(is_running=Mock(side_effect=[False, True]), start=Mock())
        cast(Any, cog).rotate_presence = loop
        await cog.on_ready()
        await cog.on_ready()

        loop.start.assert_called_once_with()

    async def test_before_loop_waits_for_discord_ready(self):
        cog, bot = self.make_cog()
        await PresenceCog.before_rotate_presence(cog)
        bot.wait_until_ready.assert_awaited_once_with()

    def test_unload_cancels_rotation_loop(self):
        cog, _ = self.make_cog()
        loop = SimpleNamespace(cancel=Mock())
        cast(Any, cog).rotate_presence = loop
        cog.cog_unload()
        loop.cancel.assert_called_once_with()
