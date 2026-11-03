"""Cog que coordena o monitoramento e a publicação do status."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, cast

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.core.background import cancel_supervised_tasks, supervise_task
from src.core.utils import (
    BR_TZ,
    discord_timestamp,
    get_config,
    get_site_status,
    ms_to_str,
)
from src.database.database import get_database
from src.monitoring.service import StatusService
from src.monitoring.settings import MonitorSettings
from src.monitoring.types import StatusCheck, StatusState
from src.ui.components import PanelContent, edit_panel, panel
from src.ui.status_messages import STATUS_TITLE, StatusMessageManager

logger = logging.getLogger(__name__)


class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()

        self.monitor_started = False
        self.pending_status_ping_task = None

        self.settings = MonitorSettings.from_environment()
        self.service = StatusService(
            self.db,
            failure_confirmations=self.settings.failure_confirmations,
            max_gap_seconds=self.settings.max_gap_seconds,
        )
        self._status_message_manager = StatusMessageManager(
            self.bot, self.service, lambda: self.state
        )
        self.monitor.change_interval(seconds=self.settings.interval_seconds)

    async def cog_unload(self):
        loop = cast(Any, self.monitor)
        loop.cancel()
        await cancel_supervised_tasks(self.bot, owner="status")
        tasks = [
            task for task in (loop.get_task(), self.pending_status_ping_task) if task
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.pending_status_ping_task = None

    @property
    def state(self) -> StatusState:
        return self.service.state

    def _get_status_message_manager(self):
        manager = getattr(self, "_status_message_manager", None)
        if manager is None:
            manager = StatusMessageManager(self.bot, self.service, lambda: self.state)
            self._status_message_manager = manager
        return manager

    # Persistência do estado.
    async def load_state(self):
        await self.service.load()

    async def load_status_config(self):
        # Atualiza as opções usadas para compor e manter o painel de status.
        self.state["config"] = {
            "kookie_status_url": await get_config(self.db, "kookie_status_url"),
            "status_old_messages_cleanup_enabled": bool(
                await get_config(
                    self.db, "status_old_messages_cleanup_enabled", False
                )
            ),
        }
        if not self.state["config"]["status_old_messages_cleanup_enabled"]:
            self._get_status_message_manager().reset_cleanup_interval()

    def build_status_content(
        self,
        s: StatusState,
        completed_period: tuple[bool, float] | None = None,
        *,
        current_time: datetime | None = None,
    ) -> PanelContent:
        online = s["online"]
        color = 0x808080 if online is None else (0x00FF00 if online else 0xFF0000)
        icon = "⚪" if online is None else ("🟢" if online else "🔴")

        url_status = s.get("config", {}).get("kookie_status_url")
        sections = [
            (
                "Status atual",
                f"{icon} {'DESCONHECIDO' if online is None else ('ONLINE' if online else 'OFFLINE')}",
            ),
            ("Código HTTP", str(s["last_http_code"])),
            ("Tempo de resposta", f"{s['last_response_time']} ms"),
        ]
        last_check = s["last_check"]
        if last_check and last_check.tzinfo is None:
            last_check = last_check.replace(tzinfo=timezone.utc)
        checked_text = (
            f"{discord_timestamp(last_check)} · <t:{int(last_check.timestamp())}:R>"
            if last_check
            else "--"
        )
        sections.append(("Última verificação", checked_text))
        service = getattr(self, "service", None)
        max_gap = service.max_gap_seconds if service else 90
        current_time = current_time or datetime.now(timezone.utc)
        if last_check and (current_time - last_check).total_seconds() > max_gap:
            sections.append(
                ("Aviso", "⚠️ Verificação antiga; o status atual é desconhecido.")
            )
        if service and service.pending_failures:
            sections.append(
                (
                    "Confirmação de queda",
                    f"{service.pending_failures}/{service.failure_confirmations} falhas consecutivas",
                )
            )

        if online is not None:
            label = "Tempo contínuo online" if online else "Tempo contínuo offline"
            key = "continuous_online" if online else "continuous_offline"
            duration = s[key]
            started_at = s.get("last_status_change")
            if started_at is not None:
                elapsed = max(0, current_time.timestamp() - started_at)
                check_is_fresh = bool(
                    last_check
                    and (current_time - last_check).total_seconds() <= max_gap
                )
                if s.get("manual_status_start") or check_is_fresh:
                    duration = max(duration, elapsed)
            sections.append((label, ms_to_str(duration * 1000)))
        sections.append(("Total de quedas", str(s["downtimes_count"])))
        if completed_period is not None:
            was_online, duration = completed_period
            label = "online" if was_online else "offline"
            sections.append((f"Último período {label}", ms_to_str(duration * 1000)))

        return PanelContent(
            STATUS_TITLE, sections=tuple(sections), accent_color=color, url=url_status
        )

    # Recuperação, limpeza e fixação da mensagem de status.
    async def get_status_message(self, channel_id):
        return await self._get_status_message_manager().get_status_message(channel_id)

    async def find_pinned_status_message(self, channel, bot_user):
        return await self._get_status_message_manager().find_pinned_status_message(
            channel, bot_user
        )

    async def find_status_message_in_history(self, channel, bot_user):
        return await self._get_status_message_manager().find_status_message_in_history(
            channel, bot_user
        )

    async def refresh_status_message(self):
        # Atualiza a mensagem existente após uma alteração administrativa.
        channel_id = await get_config(self.db, "status_channel_id")
        if not channel_id:
            return
        message = await self.get_status_message(channel_id)
        if message:
            await edit_panel(message, panel(self.build_status_content(self.state)))

    async def cleanup_old_status_messages(self, channel, current_message):
        await self._get_status_message_manager().cleanup_old_status_messages(
            channel, current_message
        )

    async def delete_pin_notification(self, channel, pinned_message_id=None):
        await self._get_status_message_manager().delete_pin_notification(
            channel, pinned_message_id
        )

    async def sync_status_pin(self, channel, message):
        await self._get_status_message_manager().sync_status_pin(
            channel, message, self.delete_pin_notification
        )

    async def send_status_ping_notification(
        self,
        channel,
        message,
        role_id,
        expected_online,
        expected_change_ts,
        completed_period=None,
        validation_delay=8,
        delete_delay=5,
    ):
        if not channel or not role_id:
            return

        try:
            await asyncio.sleep(validation_delay)
            if not await self.is_current_status_transition(
                expected_online, expected_change_ts
            ):
                return

            status_text = "ONLINE" if expected_online else "OFFLINE"
            sent = await channel.send(
                content=f"<@&{role_id}> Status do Kookie mudou para {status_text}."
            )
            await asyncio.sleep(delete_delay)
            await sent.delete()

            if not await self.is_current_status_transition(
                expected_online, expected_change_ts
            ):
                return
            await self.refresh_status_ping_panel(
                channel, message, role_id, completed_period
            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning(
                "Falha ao enviar ou apagar ping de status (%s).", type(exc).__name__
            )

    async def refresh_status_ping_panel(
        self, channel, message, role_id, completed_period
    ):
        # Aplica a menção visual depois do aviso temporário de mudança de status.
        refreshed_message = message
        if message:
            try:
                refreshed_message = await channel.fetch_message(message.id)
            except Exception:
                refreshed_message = message

        if refreshed_message:
            try:
                await edit_panel(
                    refreshed_message,
                    panel(
                        self.build_status_content(self.state, completed_period),
                        f"<@&{role_id}>",
                    ),
                )
                await self.sync_status_pin(channel, refreshed_message)
            except Exception as exc:
                logger.warning(
                    "Falha ao aplicar menção de status (%s).", type(exc).__name__
                )

    async def is_current_status_transition(self, expected_online, expected_change_ts):
        # Confirma que a transição continua atual e o monitor está ativo.
        return (
            self.state.get("online") == expected_online
            and self.state.get("last_status_change") == expected_change_ts
            and await get_config(self.db, "status_monitor_enabled", True)
        )

    def completed_period(self, status_changed):
        if not status_changed:
            return None
        was_online = not self.state["online"]
        key = "total_online" if was_online else "total_offline"
        return was_online, self.state[key]

    async def publish_status_message(self, channel_id, completed_period):
        message = await self.get_status_message(channel_id)
        channel = self.bot.get_channel(channel_id)
        content = self.build_status_content(self.state, completed_period)

        if message:
            try:
                await edit_panel(message, panel(content))
                await self.sync_status_pin(channel, message)
            except Exception:
                logger.warning("Falha ao editar mensagem de status.")
        elif channel:
            message = await channel.send(
                view=panel(content), allowed_mentions=discord.AllowedMentions.none()
            )
            await self.service.set_message_id(message.id)
            await self.sync_status_pin(channel, message)
            logger.info("Mensagem de status enviada e registrada.")

        await self.cleanup_old_status_messages(channel, message)
        return channel, message

    async def schedule_status_change_ping(
        self, status_changed, channel, message, completed_period
    ):
        if not status_changed:
            return

        status_ping_enabled = await get_config(self.db, "status_ping_enabled", False)
        role_id = (
            await get_config(self.db, "status_role_id") if status_ping_enabled else None
        )
        if self.pending_status_ping_task and not self.pending_status_ping_task.done():
            self.pending_status_ping_task.cancel()

        if role_id and channel and message:
            self.pending_status_ping_task = supervise_task(
                self.bot,
                self.send_status_ping_notification(
                    channel,
                    message,
                    role_id,
                    self.state["online"],
                    self.state["last_status_change"],
                    completed_period,
                ),
                name="status-change-ping",
                owner="status",
            )

    async def update_state(self, st: StatusCheck) -> None:
        now_dt = st.get("timestamp") or datetime.now(BR_TZ)
        status_changed = await self.service.record_check({**st, "timestamp": now_dt})
        if status_changed is None:
            return
        if status_changed:
            logger.info(
                "Transição de status registrada: estado=%s http=%s",
                "online" if self.state["online"] else "offline",
                st.get("http_code"),
            )
        completed_period = self.completed_period(status_changed)

        chan_id = await get_config(self.db, "status_channel_id")
        await self.load_status_config()
        channel, message = await self.publish_status_message(chan_id, completed_period)
        await self.schedule_status_change_ping(
            status_changed, channel, message, completed_period
        )

    # Agendamento do monitoramento.
    @tasks.loop(seconds=60)
    async def monitor(self):
        try:
            if not await get_config(self.db, "status_monitor_enabled", True):
                return
            url = await get_config(self.db, "kookie_status_url")
            if not url:
                logger.warning("URL de status ainda não configurada no painel.")
                return
            st = await get_site_status(url)
            if not await get_config(self.db, "status_monitor_enabled", True):
                return
            await self.update_state(st)
        except Exception as exc:
            logger.warning(
                "Falha no monitor de status; nova tentativa no próximo ciclo (%s).",
                type(exc).__name__,
            )

    @monitor.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()

    # Comando manual de consulta do status.
    @app_commands.command(name="status", description="Mostra o status atual do Kookie")
    async def status_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        await self.load_status_config()
        content = self.build_status_content(self.state)
        await interaction.followup.send(view=panel(content), ephemeral=True)

    # Inicialização após conexão com o Discord.
    @commands.Cog.listener()
    async def on_ready(self):
        if self.monitor_started:
            return
        self.monitor_started = True
        try:
            await self.load_state()
            # tasks.loop realiza a primeira verificação imediatamente.
            self.monitor.start()
        except Exception:
            self.monitor_started = False
            raise
        logger.info("Monitor de status iniciado.")


async def setup(bot):
    await bot.add_cog(StatusCog(bot))
