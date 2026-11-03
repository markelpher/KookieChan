"""Testes do parsing e do processamento de anúncios."""

import asyncio
import unittest
from datetime import timedelta
from typing import cast

import aiohttp
from aiohttp import web

from src.announcements.parser import (
    AnnouncementFetchError,
    get_kookie_update,
    parse_announcements,
)
from src.core.http import close_http_session


class AnnouncementsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await close_http_session()

    def test_parse_title_description_and_date(self):
        html = """<div class="announcement-item">
          <h2 class="announcement-title"> Atualização <b>nova</b> </h2>
          <div class="announcement-description">Texto <b>importante</b>.</div>
          <time class="announcement-date">01/05/2026</time></div>"""
        result = parse_announcements(html)
        self.assertEqual(result[0]["title"], "Atualização nova")
        self.assertEqual(result[0]["description"], "Texto importante .")
        self.assertEqual(result[0]["date"].utcoffset(), timedelta(hours=-3))

    def test_missing_title_does_not_create_fake_announcement(self):
        with self.assertLogs("src.announcements.parser", level="WARNING"):
            self.assertEqual(
                parse_announcements('<div class="announcement-item"></div>'), []
            )

    def test_unrecognized_page_is_reported(self):
        with self.assertLogs("src.announcements.parser", level="WARNING"):
            self.assertEqual(
                parse_announcements("<html><body>página alterada</body></html>"), []
            )

    async def test_http_error_is_not_reported_as_empty_page(self):
        async def handle(request):
            return web.Response(status=523)

        app = web.Application()
        app.router.add_get("/", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            server = cast(asyncio.Server | None, site._server)
            self.assertIsNotNone(server)
            assert server is not None
            port = server.sockets[0].getsockname()[1]
            session = aiohttp.ClientSession()
            with self.assertRaisesRegex(AnnouncementFetchError, "523"):
                await get_kookie_update(f"http://127.0.0.1:{port}/", session=session)
            await session.close()
        finally:
            await runner.cleanup()
