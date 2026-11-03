"""Integração local: cliente REST real, HTTP simulado e Discord simulado."""

import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from aiohttp import web

from src.announcements.delivery import AnnouncementDelivery
from src.announcements.discord import AnnouncementPublisher
from src.database.announcement_repository import AnnouncementRepository
from src.database.database import Database
from src.monitoring.service import StatusService


class FakeDiscordChannel:
    id = 10

    def __init__(self):
        self.messages = []

    async def send(self, *, view, allowed_mentions):
        message = SimpleNamespace(
            id=1000 + len(self.messages),
            author=SimpleNamespace(id=55),
            components=view.children,
        )
        self.messages.append(message)
        return message

    async def history(self, *, limit, after):
        for message in reversed(self.messages):
            yield message


class IntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.row = None
        self.update = None
        self.logs = []
        self.fail_ack_once = False

        async def handler(request):
            route = request.match_info["path"]
            body = await request.json() if request.can_read_body else None
            if route == "rpc/record_status_check":
                assert body is not None
                self.row = {"id": "kookie", **body["p_state"]}
                self.logs.append(body)
                return web.Response(status=204)
            if route == "status_state" and request.method == "GET":
                return web.json_response([self.row] if self.row else [])
            if route == "updates" and request.method == "GET":
                return web.json_response(
                    [self.update]
                    if self.update and self.update["delivery_status"] == "pending"
                    else []
                )
            if route == "updates" and request.method == "POST":
                if self.update:
                    return web.json_response([])
                assert body is not None
                self.update = {
                    "id": 7,
                    **body,
                    "delivery_status": "pending",
                    "delivery_attempted_at": None,
                    "delivery_channel_id": None,
                }
                return web.json_response([self.update])
            if route == "updates" and request.method == "PATCH":
                assert body is not None
                if body.get("delivery_status") == "sent" and self.fail_ack_once:
                    self.fail_ack_once = False
                    return web.json_response(
                        {"code": "503", "message": "simulado"}, status=503
                    )
                update = self.update
                assert update is not None
                update.update(body)
                return web.json_response([self.update])
            raise AssertionError((request.method, route))

        app = web.Application()
        app.router.add_route("*", "/rest/v1/{path:.*}", handler)
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

    async def test_status_survives_rest_roundtrip_and_confirmation(self):
        service = StatusService(self.db)
        for seconds, online in ((100, True), (160, False), (220, False)):
            await service.record_check(
                {
                    "timestamp": datetime.fromtimestamp(seconds, timezone.utc),
                    "online": online,
                    "http_code": 200 if online else 503,
                    "response_time": 10,
                }
            )
        restored = StatusService(self.db)
        await restored.load()
        self.assertFalse(restored.state["online"])
        self.assertEqual(restored.state["total_online"], 120)
        self.assertEqual([item["p_online"] for item in self.logs], [True, False, False])

    async def test_delivery_recovers_discord_message_after_rest_failure(self):
        repository = AnnouncementRepository(self.db)
        await repository.insert_update(
            {
                "title": "Anúncio",
                "description": "Texto",
                "date": "2026-05-01T00:00:00-03:00",
            }
        )
        channel = FakeDiscordChannel()
        cog = object.__new__(AnnouncementPublisher)
        cog.bot = SimpleNamespace(user=SimpleNamespace(id=55))
        after = AsyncMock()
        delivery = AnnouncementDelivery(
            repository,
            lambda channel_id: channel if channel_id == 10 else None,
            cog.find_sent_update,
            cog.send_pending_update,
            after,
        )
        self.fail_ack_once = True
        with self.assertLogs("src.announcements.delivery", level="ERROR"):
            await delivery.process(channel)
        self.assertEqual(len(channel.messages), 1)
        update = self.update
        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update["delivery_status"], "pending")
        await delivery.process(channel)
        self.assertEqual(len(channel.messages), 1)
        update = self.update
        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update["delivery_status"], "sent")
        self.assertEqual(update["delivery_message_id"], 1000)
        after_args = after.await_args
        self.assertIsNotNone(after_args)
        assert after_args is not None
        self.assertFalse(after_args.args[3])
