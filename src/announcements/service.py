"""Coordena descoberta e entrega de anúncios sem depender do Discord."""

import logging
import time

from src.announcements.parser import AnnouncementFetchError, get_kookie_update
from src.announcements.types import NewAnnouncement, ParsedAnnouncement

logger = logging.getLogger(__name__)


class AnnouncementService:
    def __init__(self, repository, delivery, fetch=get_kookie_update):
        self.repository = repository
        self.delivery = delivery
        self.fetch = fetch

    async def discover(self, url: str, limit: int = 10) -> int:
        updates: list[ParsedAnnouncement] = await self.fetch(url, limit)
        inserted = 0
        for update in updates:
            record: NewAnnouncement = {
                "title": update["title"],
                "description": update["description"],
                "date": update["date"].isoformat(),
            }
            inserted += bool(
                await self.repository.insert_update(record)
            )
        return inserted

    async def discover_best_effort(self, url: str | None) -> int:
        # Tenta descobrir anúncios, sem impedir a entrega da fila existente.
        try:
            return await self.discover(url) if url else 0
        except AnnouncementFetchError as exc:
            logger.warning("Falha ao buscar anúncios; tentando fila pendente: %s", exc)
        except Exception as exc:
            logger.warning(
                "Falha ao buscar anúncios; tentando fila pendente (%s).",
                type(exc).__name__,
            )
        return 0

    async def run_cycle(self, url: str | None, channel) -> None:
        started = time.monotonic()
        discovered = await self.discover_best_effort(url)
        await self.delivery.process(channel)
        logger.info(
            "Ciclo de anúncios concluído: canal=%s novos=%s duração_ms=%d",
            getattr(channel, "id", "desconhecido"),
            discovered,
            round((time.monotonic() - started) * 1000),
        )
