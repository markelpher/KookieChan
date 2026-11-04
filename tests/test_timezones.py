"""Testes de datas, fusos horários e requisições relacionadas."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from typing import cast

import aiohttp
from aiohttp import web

from src.announcements.discord import AnnouncementPublisher
from src.announcements.parser import get_kookie_update
from src.announcements.types import DisplayAnnouncement
from src.cogs.history import HistoryCog
from src.cogs.status import StatusCog
from src.core.http import close_http_session
from src.core.utils import format_datetime_br, parse_brazilian_date
from src.monitoring.service import StatusService
from src.monitoring.types import StatusLogRecord, StatusState


class TimezoneTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await close_http_session()

    def test_format_utc_and_fixed_offset_including_historical_dst(self):
        self.assertEqual(
            format_datetime_br(datetime(2018, 12, 1, 2, tzinfo=timezone.utc)),
            "30/11/2018 23:00:00",
        )
        self.assertEqual(
            parse_brazilian_date("01/12/2018 00:00").utcoffset(), timedelta(hours=-3)
        )

    def test_update_display_shows_date_without_time(self):
        cog = object.__new__(AnnouncementPublisher)
        content = cog.build_update_content(
            [{"title": "Teste", "description": "Texto", "date": "2026-05-01T02:00:00Z"}]
        )
        self.assertIn("30/04/2026", content.sections[0][0])
        self.assertNotIn("23:00", content.sections[0][0])

    def test_status_and_history_display(self):
        status = object.__new__(StatusCog)
        state = cast(
            StatusState,
            {
                "online": True,
                "last_http_code": 200,
                "last_response_time": 1,
                "last_check": datetime(2026, 5, 1, 2, tzinfo=timezone.utc),
                "continuous_online": 0,
                "downtimes_count": 0,
                "total_online": 0,
                "total_offline": 0,
            },
        )
        content = status.build_status_content(state)
        self.assertNotIn("Total offline", [heading for heading, _ in content.sections])
        self.assertNotIn("Total online", [heading for heading, _ in content.sections])
        last_check = state["last_check"]
        assert last_check is not None
        timestamp = int(last_check.timestamp())
        self.assertEqual(
            content.sections[3][1], f"<t:{timestamp}:F> · <t:{timestamp}:R>"
        )
        history = object.__new__(HistoryCog)
        log = {
            "checked_at": "2026-05-01T02:00:00Z",
            "online": True,
            "http_code": 200,
            "response_time": 1,
        }
        footer = history.build_status_content(cast(StatusLogRecord, log)).footer
        self.assertIsNotNone(footer)
        assert footer is not None
        self.assertIn(f"<t:{timestamp}:F>", footer)
        update = {
            "date": "2026-05-01T02:00:00Z",
            "title": "Teste",
            "description": "Texto",
        }
        self.assertEqual(
            history.build_update_content(cast(DisplayAnnouncement, update)).footer,
            "Data de referência: 30/04/2026",
        )

    def test_status_shows_only_the_period_that_just_ended(self):
        status = object.__new__(StatusCog)
        state = cast(
            StatusState,
            {
                "online": True,
                "last_http_code": 200,
                "last_response_time": 1,
                "last_check": datetime(2026, 5, 1, 2, tzinfo=timezone.utc),
                "continuous_online": 0,
                "continuous_offline": 0,
                "downtimes_count": 0,
            },
        )
        ordinary = status.build_status_content(state)
        self.assertFalse(
            any(name.startswith("Último período") for name, _ in ordinary.sections)
        )
        offline = status.build_status_content(state, (False, 3600))
        periods = [
            (name, value)
            for name, value in offline.sections
            if name.startswith("Último período")
        ]
        self.assertEqual(periods, [("Último período offline", "1h 00m")])
        state["online"] = False
        online = status.build_status_content(state, (True, 120))
        periods = [
            (name, value)
            for name, value in online.sections
            if name.startswith("Último período")
        ]
        self.assertEqual(periods, [("Último período online", "2m")])

    def test_stale_and_pending_status_are_explicit(self):
        status = object.__new__(StatusCog)
        status.service = StatusService(None, max_gap_seconds=90)
        status.service.pending_failures = 1
        checked = datetime(2026, 5, 1, 2, tzinfo=timezone.utc)
        state = cast(
            StatusState,
            {
                "online": True,
                "last_http_code": 503,
                "last_response_time": 1,
                "last_check": checked,
                "continuous_online": 60,
                "downtimes_count": 0,
            },
        )
        content = status.build_status_content(
            state, current_time=checked + timedelta(seconds=91)
        )
        fields = dict(content.sections)
        self.assertIn("desconhecido", fields["Aviso"])
        self.assertIn("1/2", fields["Confirmação de queda"])
        self.assertIn(":R>", fields["Última verificação"])

    async def test_scraped_date_is_midnight_gmt_minus_three(self):
        async def handle(request):
            return web.Response(
                text='<div class="announcement-item"><span class="announcement-title">Teste</span><span class="announcement-date">01/05/2026</span></div>'
            )

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
            async with aiohttp.ClientSession() as session:
                updates = await get_kookie_update(
                    f"http://127.0.0.1:{port}/", session=session
                )
            self.assertEqual(
                updates[0]["date"].isoformat(), "2026-05-01T00:00:00-03:00"
            )
        finally:
            await runner.cleanup()
