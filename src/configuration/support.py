"""Validações, permissões e operações de suporte à configuração."""

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Mapping
from datetime import datetime
from typing import TypedDict, cast
from urllib.parse import urlsplit

import discord
from discord.ui import Modal

from src.core.background import supervise_task
from src.core.utils import BR_TZ, get_config, parse_brazilian_date
from src.ui.components import Panel, PanelContent

logger = logging.getLogger("src.cogs.config")


class DashboardSettings(TypedDict):
    status_channel_id: int | str | None
    update_channel_id: int | str | None
    kookie_status_url: str | None
    kookie_update_url: str | None
    status_monitor_enabled: bool
    announcements_enabled: bool
    status_old_messages_cleanup_enabled: bool
    status_ping_enabled: bool
    update_ping_enabled: bool
    status_role_id: int | str | None
    update_role_id: int | str | None


class MonitorURLSettings(TypedDict, total=False):
    kookie_status_url: str
    kookie_update_url: str


DEFAULT_DASHBOARD_SETTINGS: DashboardSettings = {
    "status_channel_id": None,
    "update_channel_id": None,
    "kookie_status_url": None,
    "kookie_update_url": None,
    "status_monitor_enabled": True,
    "announcements_enabled": True,
    "status_old_messages_cleanup_enabled": False,
    "status_ping_enabled": False,
    "update_ping_enabled": False,
    "status_role_id": None,
    "update_role_id": None,
}


def is_authorized_admin(interaction):
    # A instância oficial só aceita configuração no seu único servidor.
    guild = interaction.guild
    if guild is None or not interaction.permissions.administrator:
        return False
    guilds = interaction.client.guilds
    return len(guilds) == 1 and guilds[0].id == guild.id


def validate_monitor_url(value):
    value = value.strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Informe uma URL http:// ou https:// válida, sem usuário ou senha."
        )
    host = parsed.hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("URLs locais ou internas não são permitidas.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Endereços IP privados ou reservados não são permitidos.")
    return value


async def validate_monitor_url_destination(value):
    # Impede hostname público que resolva para IP privado/local (SSRF).
    value = validate_monitor_url(value)
    host = urlsplit(value).hostname
    try:
        results = await asyncio.get_running_loop().getaddrinfo(
            host, None, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValueError("Não foi possível resolver o domínio informado.") from exc
    if not results or any(
        not ipaddress.ip_address(item[4][0]).is_global for item in results
    ):
        raise ValueError("O domínio resolve para um endereço privado ou reservado.")
    return value


async def validate_monitor_urls(status_value, update_value):
    urls = collect_monitor_urls(status_value, update_value)
    for url in urls.values():
        await validate_monitor_url_destination(url)
    return urls


def collect_monitor_urls(
    status_value: str | None, update_value: str | None
) -> MonitorURLSettings:
    # Valida URLs preenchidas; campos vazios preservam a configuração atual.
    urls: MonitorURLSettings = {}
    if status_value and status_value.strip():
        urls["kookie_status_url"] = validate_monitor_url(status_value)
    if update_value and update_value.strip():
        urls["kookie_update_url"] = validate_monitor_url(update_value)
    return urls


async def send_temporary_confirmation(interaction, message, delay=10):
    confirmation = await interaction.followup.send(message, ephemeral=True, wait=True)
    if confirmation is None:
        logger.warning("Discord não retornou a mensagem da confirmação temporária.")
        return

    async def delete_confirmation():
        await asyncio.sleep(delay)
        try:
            # Use o ID da mensagem exata retornada pelo follow-up; não toque
            # na resposta original, que é o painel Components V2.
            await confirmation.delete()
        except discord.HTTPException:
            logger.debug("A confirmação temporária já havia sido removida.")

    supervise_task(
        interaction.client,
        delete_confirmation(),
        name="delete-temporary-confirmation",
        owner="config",
    )


async def require_admin(interaction):
    # Valida a permissão enviada pelo Discord em cada interação do painel.
    if is_authorized_admin(interaction):
        return True
    await interaction.response.send_message(
        "Apenas administradores do servidor autorizado podem usar este painel.",
        ephemeral=True,
    )
    return False


class AdminPanel(Panel):
    async def interaction_check(self, interaction):
        return await require_admin(interaction)


class AdminModal(Modal):
    async def interaction_check(self, interaction):
        return await require_admin(interaction)


async def get_dashboard_content(db) -> PanelContent:
    settings = await get_config_values(
        db,
        tuple(DEFAULT_DASHBOARD_SETTINGS),
        DEFAULT_DASHBOARD_SETTINGS,
    )
    return build_dashboard_content(cast(DashboardSettings, settings))


def build_dashboard_content(settings: DashboardSettings) -> PanelContent:
    # Converte configurações já carregadas no conteúdo visual do painel.
    status_channel_id = settings["status_channel_id"]
    update_channel_id = settings["update_channel_id"]
    status_url = settings["kookie_status_url"] or "Não definida"
    update_url = settings["kookie_update_url"] or "Não definida"
    status_enabled = settings["status_monitor_enabled"]
    announcements_enabled = settings["announcements_enabled"]
    status_cleanup_enabled = settings["status_old_messages_cleanup_enabled"]
    status_ping = settings["status_ping_enabled"]
    update_ping = settings["update_ping_enabled"]
    status_role_id = settings["status_role_id"]
    update_role_id = settings["update_role_id"]

    st_chan = f"<#{status_channel_id}>" if status_channel_id else "Não definido"
    up_chan = f"<#{update_channel_id}>" if update_channel_id else "Não definido"

    st_ping_status = "✅ Ativado" if status_ping else "❌ Desativado"
    up_ping_status = "✅ Ativado" if update_ping else "❌ Desativado"

    st_role_mention = f"<@&{status_role_id}>" if status_role_id else "Não definido"
    up_role_mention = f"<@&{update_role_id}>" if update_role_id else "Não definido"

    return PanelContent(
        title="Painel administrativo",
        description="Boas-vindas ao centro de controle!\nGerencie canais, URLs e notificações do bot abaixo.",
        sections=(
            (
                "Monitoramento",
                f"Canal de status: {st_chan}\nCanal de anúncios: {up_chan}",
            ),
            ("URLs monitoradas", f"Status: {status_url}\nAnúncios: {update_url}"),
            (
                "Serviços automáticos",
                f"Monitor de status: {'✅ Ativado' if status_enabled else '❌ Desativado'}\n"
                f"Anúncios automáticos: {'✅ Ativados' if announcements_enabled else '❌ Desativados'}",
            ),
            (
                "Histórico de status",
                "Limpeza automática: "
                f"{'✅ Ativada' if status_cleanup_enabled else '❌ Desativada'}",
            ),
            (
                "Notificações de status",
                f"Status: {st_ping_status}\nCargo: {st_role_mention}",
            ),
            (
                "Notificações de anúncios",
                f"Status: {up_ping_status}\nCargo: {up_role_mention}",
            ),
        ),
        accent_color=0x2ECC71,
        footer="Apenas administradores podem ver este painel.",
    )


async def get_config_values(
    db, keys: tuple[str, ...], defaults: Mapping[str, object] | None = None
) -> dict[str, str | int | bool | None]:
    defaults = defaults or {}
    if hasattr(db, "get_configs"):
        stored = await db.get_configs(keys)
        return {
            key: stored.get(key) if stored.get(key) is not None else defaults.get(key)
            for key in keys
        }  # type: ignore[return-value]
    values = await asyncio.gather(
        *(get_config(db, key, defaults.get(key)) for key in keys)
    )
    return dict(zip(keys, values))  # type: ignore[return-value]


async def apply_data_action(status_cog, action, value):
    # Aplica a operação de métricas selecionada no painel administrativo.
    if action == "sync":
        if not value:
            raise ValueError("Informe uma data para sincronizar.")
        await status_cog.service.synchronize_start(
            parse_brazilian_date(value),
            datetime.now(BR_TZ),
        )
    else:
        await status_cog.service.reset_metrics(datetime.now(BR_TZ))


async def delete_previous_status_message(channel, previous_id, message, bot_user):
    # Remove a mensagem anterior do bot sem bloquear a recuperação atual.
    previous_message = None
    if previous_id and previous_id != message.id:
        try:
            previous_message = await channel.fetch_message(previous_id)
        except Exception:
            return

    if (
        previous_message
        and bot_user
        and previous_message.id != message.id
        and previous_message.author.id == bot_user.id
    ):
        try:
            await previous_message.delete()
        except Exception:
            pass
