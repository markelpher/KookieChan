"""Recuperação, fixação e limpeza das mensagens de status no Discord."""

import logging
import time

import discord

from src.ui.components import message_contains_title

STATUS_TITLE = "Status do Kookie"
STATUS_MESSAGE_HISTORY_SCAN_LIMIT = 200
STATUS_PIN_NOTIFICATION_HISTORY_SCAN_LIMIT = 25
STATUS_HISTORY_CLEANUP_INTERVAL_SECONDS = 15 * 60
logger = logging.getLogger("src.cogs.status")


class StatusMessageManager:
    def __init__(self, bot, service, get_state):
        self.bot = bot
        self.service = service
        self._get_state = get_state
        self._last_status_history_cleanup = 0.0

    @property
    def state(self):
        return self._get_state()

    def reset_cleanup_interval(self):
        self._last_status_history_cleanup = 0.0

    async def get_status_message(self, channel_id):
        bot_user = getattr(self.bot, "user", None)
        if bot_user is None:
            return None
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return None

        msg_id = self.state.get("status_message_id")
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                if msg.author.id == bot_user.id and message_contains_title(
                    msg, STATUS_TITLE
                ):
                    return msg
                else:
                    await self.service.set_message_id(None)
            except discord.NotFound:
                await self.service.set_message_id(None)
            except Exception:
                pass

        message = await self.find_pinned_status_message(channel, bot_user)
        if message:
            return message
        return await self.find_status_message_in_history(channel, bot_user)

    async def find_pinned_status_message(self, channel, bot_user):
        # Recupera primeiro das fixadas para não depender do limite do histórico.
        try:
            pinned_messages = await channel.pins()
        except Exception as exc:
            logger.warning(
                "Falha ao procurar mensagem de status fixada (%s).",
                type(exc).__name__,
            )
            return None

        for message in pinned_messages:
            if message.author.id == bot_user.id and message_contains_title(
                message, STATUS_TITLE
            ):
                await self.service.set_message_id(message.id)
                logger.info("Mensagem de status recuperada das fixadas.")
                return message
        return None

    async def find_status_message_in_history(self, channel, bot_user):
        # Recupera do histórico uma mensagem de status do próprio bot.
        try:
            async for msg in channel.history(limit=STATUS_MESSAGE_HISTORY_SCAN_LIMIT):
                if msg.author.id == bot_user.id:
                    if message_contains_title(msg, STATUS_TITLE):
                        await self.service.set_message_id(msg.id)
                        logger.info("Mensagem de status recuperada.")
                        return msg
        except Exception as e:
            logger.warning(
                "Erro ao procurar mensagem de status (%s).", type(e).__name__
            )

        return None

    async def cleanup_old_status_messages(self, channel, current_message):
        if not channel or not current_message:
            return
        if not self.state.get("config", {}).get(
            "status_old_messages_cleanup_enabled", False
        ):
            return

        now = time.monotonic()
        if (
            now - getattr(self, "_last_status_history_cleanup", 0.0)
            < STATUS_HISTORY_CLEANUP_INTERVAL_SECONDS
        ):
            return
        self._last_status_history_cleanup = now

        bot_user = getattr(self.bot, "user", None)
        if bot_user is None:
            return
        try:
            async for message in channel.history(limit=STATUS_MESSAGE_HISTORY_SCAN_LIMIT):
                if message.id == current_message.id:
                    continue
                if message.author.id != bot_user.id:
                    continue
                if not message_contains_title(message, STATUS_TITLE):
                    continue
                try:
                    await message.delete()
                except Exception as exc:
                    logger.warning(
                        "Falha ao apagar mensagem antiga de status (%s).",
                        type(exc).__name__,
                    )
        except Exception as exc:
            logger.warning(
                "Falha ao procurar mensagens antigas de status (%s).",
                type(exc).__name__,
            )

    async def delete_pin_notification(self, channel, pinned_message_id=None):
        bot_user = getattr(self.bot, "user", None)
        if bot_user is None:
            return
        try:
            async for msg in channel.history(
                limit=STATUS_PIN_NOTIFICATION_HISTORY_SCAN_LIMIT
            ):
                if msg.type != discord.MessageType.pins_add:
                    continue
                if msg.author.id != bot_user.id:
                    continue
                await msg.delete()
        except Exception as e:
            logger.warning(
                "Falha ao apagar notificação de fixação (%s).", type(e).__name__
            )

    async def sync_status_pin(self, channel, message, delete_pin_notification=None):
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
            if not message_contains_title(pinned, STATUS_TITLE):
                continue

            try:
                await pinned.unpin(reason="Substituindo mensagem fixa de status")
            except Exception as e:
                logger.warning("Falha ao desafixar status (%s).", type(e).__name__)

        if already_pinned:
            return

        try:
            await message.pin(reason="Mensagem fixa de status do Kookie")
            if delete_pin_notification:
                await delete_pin_notification(channel, message.id)
            else:
                await self.delete_pin_notification(channel, message.id)
        except discord.HTTPException as e:
            # Ignora erro de mensagem já fixada e segue o fluxo.
            if getattr(e, "code", None) != 30003:
                logger.warning("Falha ao fixar status (%s).", type(e).__name__)
        except Exception as e:
            logger.warning("Falha ao fixar status (%s).", type(e).__name__)
