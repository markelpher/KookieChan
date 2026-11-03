"""Fila persistente para publicação de anúncios, independente do Discord."""

import logging
from datetime import datetime, timedelta, timezone

from src.announcements.types import PendingAnnouncement

logger = logging.getLogger(__name__)


def marker(update_id):
    return f"[kookie-update:{update_id}]"


def has_delivery_marker(message, delivery_marker):
    # Aceita apenas a linha de identificação, não texto arbitrário do anúncio.

    def contains(component):
        content = getattr(component, "content", "") or ""
        if content.splitlines()[:1] == [f"-# {delivery_marker}"]:
            return True
        return any(contains(child) for child in getattr(component, "children", ()))

    return any(contains(component) for component in message.components)


class AnnouncementDelivery:
    def __init__(
        self, database, resolve_channel, find_message, send_message, after_delivery
    ):
        self.database = database
        self.resolve_channel = resolve_channel
        self.find_message = find_message
        self.send_message = send_message
        self.after_delivery = after_delivery

    async def _recover_uncertain_delivery(self, update: PendingAnnouncement):
        # Localiza a mensagem da tentativa anterior sem reenviar às cegas.
        channel_id = update.get("delivery_channel_id")
        channel = self.resolve_channel(int(channel_id)) if channel_id else None
        if channel is None:
            raise RuntimeError(
                "Canal da tentativa anterior indisponível; envio mantido pendente."
            )
        since = datetime.fromisoformat(
            (update["delivery_attempted_at"] or "").replace("Z", "+00:00")
        ) - timedelta(seconds=60)
        message = await self.find_message(channel, marker(update["id"]), since)
        return channel, message

    async def _process_update(self, update: PendingAnnouncement, channel) -> None:
        # Isola falhas por item para a fila continuar no próximo.
        try:
            current_channel = channel
            attempted_at = update.get("delivery_attempted_at")
            if attempted_at:
                current_channel, message = await self._recover_uncertain_delivery(
                    update
                )
            else:
                update = await self.database.start_update_delivery(
                    update["id"], channel.id, datetime.now(timezone.utc).isoformat()
                )
                message = None
            is_new = message is None
            if is_new:
                message = await self.send_message(current_channel, update)
            if message is None:
                raise RuntimeError("Discord não retornou a mensagem enviada.")
            await self.database.mark_update_sent(
                update["id"], message.id, datetime.now(timezone.utc).isoformat()
            )
            try:
                await self.after_delivery(current_channel, message, update, is_new)
            except Exception as exc:
                logger.error(
                    "Anúncio %s enviado, mas falhou a ação posterior (%s).",
                    update["id"],
                    type(exc).__name__,
                )
        except Exception as exc:
            logger.error(
                "Falha ao publicar anúncio %s; permanece pendente (%s).",
                update["id"],
                type(exc).__name__,
            )

    async def process(self, channel) -> None:
        updates = await self.database.list_pending_updates()
        for update in updates:
            await self._process_update(update, channel)
