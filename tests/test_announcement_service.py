"""Testes da coordenação de busca e persistência de anúncios."""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from src.announcements.parser import AnnouncementFetchError
from src.announcements.service import AnnouncementService


class AnnouncementServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repository = AsyncMock()
        self.delivery = AsyncMock()
        self.fetch = AsyncMock()
        self.service = AnnouncementService(self.repository, self.delivery, self.fetch)

    async def test_discover_serializes_dates(self):
        date = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.fetch.return_value = [
            {"title": "Teste", "description": "Texto", "date": date}
        ]
        await self.service.discover("https://example.org", limit=3)
        self.fetch.assert_awaited_once_with("https://example.org", 3)
        self.repository.insert_update.assert_awaited_once_with(
            {"title": "Teste", "description": "Texto", "date": date.isoformat()}
        )

    async def test_cycle_logs_success_context_and_new_record_count(self):
        date = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.fetch.return_value = [
            {"title": "Novo", "description": "Texto", "date": date},
            {"title": "Duplicado", "description": "Texto", "date": date},
        ]
        self.repository.insert_update.side_effect = [True, False]
        channel = type("Channel", (), {"id": 987})()

        with self.assertLogs("src.announcements.service", level="INFO") as captured:
            await self.service.run_cycle("https://example.org", channel)

        self.assertIn("canal=987 novos=1", captured.output[-1])
        self.delivery.process.assert_awaited_once_with(channel)

    async def test_cycle_processes_queue_after_fetch_or_persistence_failure(self):
        for failure in ("fetch", "persistence"):
            with self.subTest(failure=failure):
                self.delivery.reset_mock()
                self.fetch.reset_mock(side_effect=True, return_value=True)
                self.repository.reset_mock(side_effect=True)
                self.fetch.return_value = [
                    {
                        "title": "Teste",
                        "description": "Texto",
                        "date": datetime.now(timezone.utc),
                    }
                ]
                if failure == "fetch":
                    self.fetch.side_effect = AnnouncementFetchError("indisponível")
                else:
                    self.repository.insert_update.side_effect = RuntimeError(
                        "indisponível"
                    )
                with self.assertLogs("src.announcements.service", level="WARNING"):
                    await self.service.run_cycle("https://example.org", "channel")
                self.delivery.process.assert_awaited_once_with("channel")
