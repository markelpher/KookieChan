"""Publicação de anúncios no Discord."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime

import discord

from src.announcements.delivery import has_delivery_marker, marker
from src.announcements.types import (
    DeliveryAnnouncement,
    DisplayAnnouncement,
    PendingAnnouncement,
)
from src.core.background import supervise_task
from src.core.utils import announcement_date, get_config
from src.ui.components import PanelContent, edit_panel, message_contains_title, panel

UPDATE_TITLE = "📢 Última atualização do Kookie"
logger = logging.getLogger(__name__)


class AnnouncementPublisher:
    def __init__(self, bot, database):
        self.bot = bot
        self.db = database

    def build_update_content(
        self, update_items: Sequence[DisplayAnnouncement]
    ) -> PanelContent:
        sections = []
        for update in update_items:
            date = update["date"]
            if isinstance(date, str):
                date = datetime.fromisoformat(date.replace("Z", "+00:00"))
            date_str = announcement_date(date)
            sections.append((f"{update['title']} · {date_str}", update["description"]))
        return PanelContent(
            UPDATE_TITLE, sections=tuple(sections), accent_color=0xFFD700
        )

    async def clear_update_ping(self, message, delay=3):
        if not message:
            return
        try:
            await asyncio.sleep(delay)
            await message.delete()
        except Exception as e:
            logger.warning("Falha ao limpar ping de anúncio (%s).", type(e).__name__)

    async def delete_pin_notification(self, channel):
        bot_user = getattr(self.bot, "user", None)
        if bot_user is None:
            return
        try:
            async for msg in channel.history(limit=25):
                if msg.type != discord.MessageType.pins_add:
                    continue
                if msg.author.id != bot_user.id:
                    continue
                await msg.delete()
        except Exception as e:
            logger.warning(
                "Falha ao apagar notificação de fixação (%s).", type(e).__name__
            )

    async def sync_update_pin(self, channel, message):
        if not channel or not message:
            return

        try:
            pinned_messages = await channel.pins()
        except Exception as e:
            logger.warning(
                "Falha ao carregar mensagens fixadas (%s).", type(e).__name__
            )
            pinned_messages = []

        bot_user = getattr(self.bot, "user", None)
        already_pinned = False
        for pinned in pinned_messages:
            if pinned.id == message.id:
                already_pinned = True
                continue
            if bot_user is None or pinned.author.id != bot_user.id:
                continue
            if not message_contains_title(pinned, UPDATE_TITLE):
                continue

            try:
                await pinned.unpin(reason="Substituindo mensagem fixa de anúncio")
            except Exception as e:
                logger.warning("Falha ao desafixar anúncio (%s).", type(e).__name__)

        if already_pinned:
            return

        try:
            await message.pin(reason="Mensagem fixa de anúncio do Kookie")
            await self.delete_pin_notification(channel)
        except discord.HTTPException as e:
            if getattr(e, "code", None) != 30003:
                logger.warning("Falha ao fixar anúncio (%s).", type(e).__name__)
        except Exception as e:
            logger.warning("Falha ao fixar anúncio (%s).", type(e).__name__)

    async def send_update_ping_notification(self, channel, role_id, count):
        if not channel or not role_id:
            return
        suffix = (
            "anúncio novo publicado."
            if count == 1
            else f"{count} anúncios novos publicados."
        )
        content = f"<@&{role_id}> {suffix}"
        try:
            sent = await channel.send(content=content)
            supervise_task(
                self.bot,
                self.clear_update_ping(sent),
                name="delete-announcement-ping",
                owner="announcements",
            )
            return sent
        except Exception as e:
            logger.warning("Falha ao enviar ping de anúncio (%s).", type(e).__name__)
            return None

    async def apply_visual_update_mention(
        self, channel, message, role_id, updates, delay=3
    ):
        if not channel or not message or not role_id:
            return
        try:
            await asyncio.sleep(delay)
            refreshed_message = message
            try:
                refreshed_message = await channel.fetch_message(message.id)
            except Exception:
                pass

            prefix = f"-# {marker(updates[0]['id'])}\n<@&{role_id}>"
            await edit_panel(
                refreshed_message, panel(self.build_update_content(updates), prefix)
            )
            await self.sync_update_pin(channel, refreshed_message)
        except Exception as e:
            logger.warning("Falha ao aplicar menção de anúncio (%s).", type(e).__name__)

    async def find_sent_update(self, channel, delivery_marker, since):
        bot_user = getattr(self.bot, "user", None)
        if bot_user is None:
            return None
        async for message in channel.history(limit=None, after=since):
            if message.author.id == bot_user.id and has_delivery_marker(
                message, delivery_marker
            ):
                return message
        return None

    async def send_pending_update(self, channel, update: PendingAnnouncement):
        return await channel.send(
            view=panel(
                self.build_update_content([update]), f"-# {marker(update['id'])}"
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def notify_new_update(self, channel, message, update):
        # Envia e aplica a menção visual após uma entrega realmente nova.
        ping_enabled = await get_config(self.db, "update_ping_enabled", False)
        role_id = await get_config(self.db, "update_role_id") if ping_enabled else None
        if not role_id:
            return

        await self.send_update_ping_notification(channel, role_id, 1)
        supervise_task(
            self.bot,
            self.apply_visual_update_mention(channel, message, role_id, [update]),
            name="apply-announcement-mention",
            owner="announcements",
        )

    async def on_update_delivered(
        self, channel, message, update: DeliveryAnnouncement, is_new: bool
    ) -> None:
        await self.sync_update_pin(channel, message)
        if is_new:
            await self.notify_new_update(channel, message, update)
