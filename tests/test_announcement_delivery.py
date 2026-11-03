"""Testes da entrega e recuperação de anúncios no Discord."""

import copy
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

from src.announcements.delivery import AnnouncementDelivery, has_delivery_marker, marker


class FakeDatabase:
    def __init__(self):
        self.update = {
            "id": 1,
            "title": "Teste",
            "delivery_status": "pending",
            "delivery_attempted_at": None,
            "delivery_channel_id": None,
        }
        self.fail_mark = False

    async def list_pending_updates(self):
        return (
            [copy.deepcopy(self.update)]
            if self.update["delivery_status"] == "pending"
            else []
        )

    async def start_update_delivery(self, update_id, channel_id, attempted_at):
        self.update.update(
            delivery_attempted_at=attempted_at, delivery_channel_id=channel_id
        )
        return copy.deepcopy(self.update)

    async def mark_update_sent(self, update_id, message_id, delivered_at):
        if self.fail_mark:
            raise RuntimeError("banco indisponível")
        self.update.update(delivery_status="sent", delivery_message_id=message_id)


class DeliveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.channel = SimpleNamespace(id=10)
        self.message = SimpleNamespace(id=123)
        self.find = AsyncMock(return_value=None)
        self.send = AsyncMock(return_value=self.message)
        self.after = AsyncMock()
        self.service = AnnouncementDelivery(
            self.db,
            lambda id: self.channel if id == 10 else None,
            self.find,
            self.send,
            self.after,
        )

    async def test_failed_send_is_retried(self):
        self.send.side_effect = [RuntimeError("Discord indisponível"), self.message]
        with self.assertLogs("src.announcements.delivery", level="ERROR"):
            await self.service.process(self.channel)
        self.assertEqual(self.db.update["delivery_status"], "pending")
        await self.service.process(self.channel)
        self.assertEqual(self.db.update["delivery_status"], "sent")
        self.assertEqual(self.send.await_count, 2)
        find_args = self.find.await_args
        self.assertIsNotNone(find_args)
        assert find_args is not None
        self.assertEqual(find_args.args[1], marker(1))

    async def test_failure_on_one_update_does_not_stop_later_queue_items(self):
        second_message = SimpleNamespace(id=456)
        database = SimpleNamespace(
            list_pending_updates=AsyncMock(return_value=[{"id": 1}, {"id": 2}]),
            start_update_delivery=AsyncMock(
                side_effect=lambda update_id, channel_id, attempted_at: {
                    "id": update_id
                }
            ),
            mark_update_sent=AsyncMock(),
        )
        send = AsyncMock(side_effect=[RuntimeError("falha isolada"), second_message])
        delivery = AnnouncementDelivery(
            database,
            lambda channel_id: self.channel,
            self.find,
            send,
            self.after,
        )

        with self.assertLogs("src.announcements.delivery", level="ERROR"):
            await delivery.process(self.channel)

        self.assertEqual(send.await_count, 2)
        database.mark_update_sent.assert_awaited_once_with(2, 456, ANY)
        self.after.assert_awaited_once()

    async def test_after_delivery_failure_does_not_requeue_confirmed_send(self):
        self.after.side_effect = RuntimeError("private Discord details")

        with self.assertLogs("src.announcements.delivery", level="ERROR") as logs:
            await self.service.process(self.channel)

        self.assertEqual(self.db.update["delivery_status"], "sent")
        self.assertEqual(self.db.update["delivery_message_id"], self.message.id)
        self.send.assert_awaited_once()
        self.assertNotIn("private Discord details", logs.output[0])

    async def test_recovery_after_message_sent_but_confirmation_failed(self):
        self.db.fail_mark = True
        with self.assertLogs("src.announcements.delivery", level="ERROR"):
            await self.service.process(self.channel)
        self.db.fail_mark = False
        self.find.return_value = self.message
        await self.service.process(self.channel)
        self.assertEqual(self.send.await_count, 1)
        self.assertEqual(self.db.update["delivery_status"], "sent")
        self.assertEqual(self.db.update["delivery_message_id"], 123)
        self.after.assert_awaited_once()
        after_args = self.after.await_args
        self.assertIsNotNone(after_args)
        assert after_args is not None
        self.assertFalse(after_args.args[3])

    async def test_history_failure_does_not_send_duplicate(self):
        self.db.update.update(
            delivery_attempted_at="2026-01-01T00:00:00+00:00", delivery_channel_id=10
        )
        self.find.side_effect = RuntimeError("sem acesso ao histórico")
        with self.assertLogs("src.announcements.delivery", level="ERROR"):
            await self.service.process(self.channel)
        self.send.assert_not_awaited()
        self.assertEqual(self.db.update["delivery_status"], "pending")

    async def test_missing_previous_channel_does_not_resend_elsewhere(self):
        self.db.update.update(
            delivery_attempted_at="2026-01-01T00:00:00+00:00", delivery_channel_id=99
        )
        with self.assertLogs("src.announcements.delivery", level="ERROR"):
            await self.service.process(self.channel)
        self.send.assert_not_awaited()
        self.assertEqual(self.db.update["delivery_status"], "pending")

    async def test_uncertain_delivery_recovers_from_original_channel_and_time_window(
        self,
    ):
        attempted_at = "2026-01-01T00:01:00+00:00"
        self.db.update.update(
            delivery_attempted_at=attempted_at,
            delivery_channel_id=10,
        )
        self.find.return_value = self.message

        await self.service.process(self.channel)

        self.find.assert_awaited_once_with(
            self.channel,
            marker(1),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.send.assert_not_awaited()
        self.assertEqual(self.db.update["delivery_status"], "sent")

    async def test_completed_delivery_is_not_sent_again(self):
        await self.service.process(self.channel)
        await self.service.process(self.channel)
        self.assertEqual(self.send.await_count, 1)
        self.after.assert_awaited_once()

    def test_marker_must_be_first_line_not_announcement_content(self):
        message = SimpleNamespace(
            components=[
                SimpleNamespace(
                    children=[
                        SimpleNamespace(content="-# [kookie-update:1]\n\n# Título")
                    ]
                )
            ]
        )
        self.assertTrue(has_delivery_marker(message, marker(1)))
        self.assertFalse(has_delivery_marker(message, marker(10)))
        message.components[0].children[0].content = "# Título\n[kookie-update:1]"
        self.assertFalse(has_delivery_marker(message, marker(1)))
