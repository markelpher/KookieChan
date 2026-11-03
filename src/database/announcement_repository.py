"""Persistência dos anúncios e sua fila de entrega no Supabase."""

from src.announcements.types import AnnouncementRecord, PendingAnnouncement


class AnnouncementRepository:
    def __init__(self, database):
        self.database = database

    async def list_updates(self, limit: int) -> list[AnnouncementRecord] | None:
        return await self.database.request(
            "GET",
            "updates",
            params={"select": "*", "order": "timestamp.desc", "limit": str(limit)},
        )

    async def insert_update(self, update: AnnouncementRecord) -> bool:
        rows = await self.database.request(
            "POST",
            "updates",
            params={"on_conflict": "title"},
            data=update,
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return bool(rows)

    async def list_pending_updates(
        self, limit: int = 100
    ) -> list[PendingAnnouncement] | None:
        return await self.database.request(
            "GET",
            "updates",
            params={
                "select": "*",
                "delivery_status": "eq.pending",
                "order": "timestamp.asc,id.asc",
                "limit": str(limit),
            },
        )

    async def start_update_delivery(
        self, update_id: int, channel_id: int, attempted_at: str
    ) -> PendingAnnouncement:
        rows = await self.database.request(
            "PATCH",
            "updates",
            params={
                "id": f"eq.{update_id}",
                "delivery_status": "eq.pending",
                "delivery_attempted_at": "is.null",
            },
            data={
                "delivery_attempted_at": attempted_at,
                "delivery_channel_id": channel_id,
            },
            prefer="return=representation",
        )
        if not rows:
            raise RuntimeError(
                "Não foi possível registrar a tentativa de envio; atualize a fila."
            )
        return rows[0]

    async def mark_update_sent(
        self, update_id: int, message_id: int, delivered_at: str
    ) -> None:
        rows = await self.database.request(
            "PATCH",
            "updates",
            params={"id": f"eq.{update_id}", "delivery_status": "eq.pending"},
            data={
                "delivery_status": "sent",
                "delivery_message_id": message_id,
                "delivered_at": delivered_at,
            },
            prefer="return=representation",
        )
        if not rows:
            raise RuntimeError("Não foi possível confirmar o envio do anúncio.")
