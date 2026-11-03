"""Testes da publicação de anúncios nos canais do Discord."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.announcements.delivery import marker
from src.announcements.discord import AnnouncementPublisher
from src.announcements.types import DeliveryAnnouncement, PendingAnnouncement


class PublisherTest(unittest.IsolatedAsyncioTestCase):
    def make_publisher(self):
        bot = SimpleNamespace(
            user=SimpleNamespace(id=10), _kookie_background_tasks=set()
        )
        return AnnouncementPublisher(bot, object()), bot

    def test_build_update_content_formats_dates_and_sections(self):
        publisher, _ = self.make_publisher()
        content = publisher.build_update_content(
            [
                {"title": "Um", "description": "Texto", "date": "2026-05-01T00:00:00Z"},
                {
                    "title": "Dois",
                    "description": "Outro",
                    "date": datetime(2026, 5, 2, tzinfo=timezone.utc).isoformat(),
                },
            ]
        )

        self.assertEqual(len(content.sections), 2)
        self.assertIn("Um", content.sections[0][0])
        self.assertEqual(content.sections[0][1], "Texto")

    async def test_clear_ping_deletes_message_and_handles_failure(self):
        publisher, _ = self.make_publisher()
        message = SimpleNamespace(delete=AsyncMock())
        await publisher.clear_update_ping(message, delay=0)
        message.delete.assert_awaited_once()

        message.delete.side_effect = RuntimeError("private")
        with self.assertLogs("src.announcements.discord", level="WARNING") as logs:
            await publisher.clear_update_ping(message, delay=0)
        self.assertNotIn("private", logs.output[0])

    async def test_sync_pin_replaces_previous_bot_pin_and_cleans_notification(self):
        publisher, _ = self.make_publisher()
        old_pin = SimpleNamespace(
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
        message = SimpleNamespace(id=2, pin=AsyncMock())
        channel = SimpleNamespace(pins=AsyncMock(return_value=[old_pin]), history=None)
        publisher.delete_pin_notification = AsyncMock()

        await publisher.sync_update_pin(channel, message)

        old_pin.unpin.assert_awaited_once()
        message.pin.assert_awaited_once()
        publisher.delete_pin_notification.assert_awaited_once_with(channel)

    async def test_sync_pin_preserves_status_panel_from_same_bot(self):
        publisher, _ = self.make_publisher()
        status_pin = SimpleNamespace(
            id=1,
            author=SimpleNamespace(id=10),
            components=[
                SimpleNamespace(
                    children=[SimpleNamespace(content="# Status do Kookie")]
                )
            ],
            unpin=AsyncMock(),
        )
        message = SimpleNamespace(id=2, pin=AsyncMock())
        channel = SimpleNamespace(pins=AsyncMock(return_value=[status_pin]))
        publisher.delete_pin_notification = AsyncMock()

        await publisher.sync_update_pin(channel, message)

        status_pin.unpin.assert_not_awaited()
        message.pin.assert_awaited_once()

    async def test_sync_pin_skips_repin_if_already_pinned_and_keeps_other_authors(self):
        publisher, _ = self.make_publisher()
        foreign = SimpleNamespace(
            id=1, author=SimpleNamespace(id=99), unpin=AsyncMock()
        )
        existing = SimpleNamespace(
            id=2, author=SimpleNamespace(id=10), unpin=AsyncMock()
        )
        message = SimpleNamespace(id=2, pin=AsyncMock())
        channel = SimpleNamespace(pins=AsyncMock(return_value=[foreign, existing]))

        await publisher.sync_update_pin(channel, message)

        foreign.unpin.assert_not_awaited()
        existing.unpin.assert_not_awaited()
        message.pin.assert_not_awaited()

    async def test_sync_pin_continues_after_pin_lookup_failure(self):
        publisher, _ = self.make_publisher()
        channel = SimpleNamespace(pins=AsyncMock(side_effect=RuntimeError()))
        message = SimpleNamespace(id=2, pin=AsyncMock())
        publisher.delete_pin_notification = AsyncMock()

        await publisher.sync_update_pin(channel, message)

        message.pin.assert_awaited_once()

    async def test_send_ping_and_schedule_cleanup(self):
        publisher, bot = self.make_publisher()
        message = SimpleNamespace(delete=AsyncMock())
        channel = SimpleNamespace(send=AsyncMock(return_value=message))

        def discard_task(bot, coroutine, **kwargs):
            coroutine.close()

        with patch(
            "src.announcements.discord.supervise_task", side_effect=discard_task
        ) as supervise:
            sent = await publisher.send_update_ping_notification(channel, 123, 2)

        self.assertIs(sent, message)
        self.assertIn(
            "2 anúncios novos publicados.", channel.send.await_args.kwargs["content"]
        )
        supervise.assert_called_once()
        self.assertIs(bot, publisher.bot)

    async def test_ping_is_skipped_without_channel_or_role_and_returns_none_on_failure(
        self,
    ):
        publisher, _ = self.make_publisher()
        self.assertIsNone(await publisher.send_update_ping_notification(None, 123, 1))
        self.assertIsNone(
            await publisher.send_update_ping_notification(object(), None, 1)
        )

        channel = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("secret")))
        with self.assertLogs("src.announcements.discord", level="WARNING") as logs:
            self.assertIsNone(
                await publisher.send_update_ping_notification(channel, 123, 1)
            )
        self.assertNotIn("secret", logs.output[0])

    async def test_visual_mention_edit_failure_is_logged_without_details(self):
        publisher, _ = self.make_publisher()
        message = SimpleNamespace(id=12)
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        with (
            patch("src.announcements.discord.asyncio.sleep", new=AsyncMock()),
            patch(
                "src.announcements.discord.edit_panel",
                new=AsyncMock(side_effect=RuntimeError("private Discord details")),
            ),
            self.assertLogs("src.announcements.discord", level="WARNING") as logs,
        ):
            await publisher.apply_visual_update_mention(
                channel, message, 123, [{"id": 7}], delay=0
            )

        self.assertNotIn("private Discord details", logs.output[0])

    async def test_find_sent_update_matches_only_bot_messages_with_marker(self):
        publisher, _ = self.make_publisher()
        target = marker(5)
        messages = [
            SimpleNamespace(author=SimpleNamespace(id=99), content=target),
            SimpleNamespace(author=SimpleNamespace(id=10), components=[]),
            SimpleNamespace(
                author=SimpleNamespace(id=10),
                components=[
                    SimpleNamespace(content=f"-# {target}\ntext", children=[]),
                ],
            ),
        ]

        async def history(**kwargs):
            for message in messages:
                yield message

        channel = SimpleNamespace(history=history)
        found = await publisher.find_sent_update(
            channel, target, datetime.now(timezone.utc)
        )
        self.assertIs(found, messages[2])

    async def test_send_pending_update_disables_mentions(self):
        publisher, _ = self.make_publisher()
        channel = SimpleNamespace(send=AsyncMock(return_value="sent"))
        update: PendingAnnouncement = {
            "id": 5,
            "title": "Teste",
            "description": "Texto",
            "date": "2026-05-01T00:00:00Z",
            "delivery_status": "pending",
            "delivery_attempted_at": None,
            "delivery_channel_id": None,
        }

        result = await publisher.send_pending_update(channel, update)

        self.assertEqual(result, "sent")
        allowed_mentions = channel.send.await_args.kwargs["allowed_mentions"]
        self.assertFalse(allowed_mentions.everyone)
        self.assertFalse(allowed_mentions.roles)
        self.assertFalse(allowed_mentions.users)

    async def test_delivery_runs_pin_and_skips_ping_for_existing_delivery(self):
        publisher, _ = self.make_publisher()
        publisher.sync_update_pin = AsyncMock()
        update: DeliveryAnnouncement = {"id": 8}
        channel, message = object(), object()
        await publisher.on_update_delivered(channel, message, update, False)

        publisher.sync_update_pin.assert_awaited_once_with(channel, message)

    async def test_delivery_schedules_visual_role_mention_for_new_delivery(self):
        publisher, _ = self.make_publisher()
        publisher.sync_update_pin = AsyncMock()
        publisher.send_update_ping_notification = AsyncMock()
        db = SimpleNamespace()
        publisher.db = db
        update: DeliveryAnnouncement = {"id": 8}

        def discard_task(bot, coroutine, **kwargs):
            coroutine.close()

        with (
            patch(
                "src.announcements.discord.get_config",
                new=AsyncMock(side_effect=[True, 77]),
            ),
            patch(
                "src.announcements.discord.supervise_task", side_effect=discard_task
            ) as supervise,
        ):
            await publisher.on_update_delivered(object(), object(), update, True)

        publisher.send_update_ping_notification.assert_awaited_once()
        supervise.assert_called_once()
