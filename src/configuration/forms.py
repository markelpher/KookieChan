"""Formulários e fluxos de interação da configuração administrativa."""

import logging
from typing import cast

import discord
from discord.ext import commands
from discord.ui import TextInput

from src.cogs.status import StatusCog
from src.configuration.support import (
    AdminModal,
    apply_data_action,
    delete_previous_status_message,
    get_config,
    get_config_values,
    send_temporary_confirmation,
    validate_monitor_urls,
)
from src.configuration.views import save_modal_settings, show_dashboard
from src.database.database import get_database
from src.ui.components import edit_panel, message_contains_title, panel

logger = logging.getLogger("src.cogs.config")


def select_default_values(value, value_type):
    if value is None:
        return discord.utils.MISSING
    return [discord.SelectDefaultValue(id=int(value), type=value_type)]


def toggle_select(label, enabled, *, required=True):
    # Cria um seletor reutilizável de ativação ou desativação.
    return discord.ui.Select(
        placeholder=label,
        min_values=1 if required else 0,
        required=required,
        options=[
            discord.SelectOption(label="Ativado", value="true", default=enabled),
            discord.SelectOption(
                label="Desativado", value="false", default=not enabled
            ),
        ],
    )


async def restore_status_message(interaction, status_cog, channel, message_id):
    # Valida, registra e fixa a mensagem escolhida pelo administrador.
    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        await interaction.response.send_message(
            "Não encontrei essa mensagem no canal de status configurado.",
            ephemeral=True,
        )
        return
    except Exception as exc:
        logger.warning("Falha ao buscar mensagem de status (%s).", type(exc).__name__)
        await interaction.response.send_message(
            "Falha ao buscar a mensagem.", ephemeral=True
        )
        return

    previous_id = status_cog.state.get("status_message_id")
    await status_cog.load_status_config()
    bot_user = interaction.client.user
    try:
        if (
            bot_user is None
            or message.author.id != bot_user.id
            or not message_contains_title(message, "Status do Kookie")
        ):
            raise ValueError("A mensagem não é uma mensagem de status deste bot.")
        await edit_panel(
            message, panel(status_cog.build_status_content(status_cog.state))
        )
        await status_cog.service.set_message_id(message_id)
        await status_cog.sync_status_pin(channel, message)
        await status_cog.cleanup_old_status_messages(channel, message)
    except Exception as exc:
        logger.warning(
            "Falha ao atualizar mensagem de status (%s).", type(exc).__name__
        )
        await interaction.response.send_message(
            "Não foi possível recuperar a mensagem de status.", ephemeral=True
        )
        return

    await delete_previous_status_message(channel, previous_id, message, bot_user)

    await interaction.response.send_message(
        f"Mensagem de status recuperada com sucesso: [ir para mensagem]({message.jump_url})",
        ephemeral=True,
    )


class DataModal(AdminModal, title="Tempo & Dados"):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.action_select = discord.ui.Select(
            placeholder="Escolha uma ação",
            options=[
                discord.SelectOption(label="Sincronizar data", value="sync"),
                discord.SelectOption(label="Zerar métricas", value="reset"),
            ],
        )
        self.data_input = TextInput(
            placeholder="Ex.: 28/08/2025 15:30 (para sincronizar)",
            required=False,
            min_length=10,
            max_length=16,
        )
        self.add_item(discord.ui.Label(text="Ação", component=self.action_select))
        self.add_item(
            discord.ui.Label(
                text="Data de início (GMT-3)",
                description="Use DD/MM/AAAA ou DD/MM/AAAA HH:MM ao sincronizar.",
                component=self.data_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        status_cog = cast(
            StatusCog | None,
            cast(commands.Bot, interaction.client).get_cog("StatusCog"),
        )
        if status_cog is None:
            return await interaction.response.send_message(
                "Monitor de status indisponível.",
                ephemeral=True,
            )

        action = self.action_select.values[0]
        value = self.data_input.value.strip()
        try:
            await apply_data_action(status_cog, action, value)
        except ValueError as exc:
            return await interaction.response.send_message(
                f"Erro: {exc}", ephemeral=True
            )
        except Exception as exc:
            logger.error(
                "Falha ao aplicar operação de métricas (%s).", type(exc).__name__
            )
            return await interaction.response.send_message(
                "Falha ao atualizar as métricas. Consulte os logs.",
                ephemeral=True,
            )

        try:
            await status_cog.refresh_status_message()
        except Exception as exc:
            logger.warning(
                "Métricas atualizadas, mas falhou a atualização da mensagem (%s).",
                type(exc).__name__,
            )

        await show_dashboard(interaction, self.db)


class UrlModal(AdminModal, title="URLs do Monitor"):
    status_url = TextInput(
        label="URL de Status",
        placeholder="Vazio mantém a URL atual",
        required=False,
        max_length=500,
    )
    update_url = TextInput(
        label="URL de anúncios",
        placeholder="Vazio mantém a URL atual",
        required=False,
        max_length=500,
    )

    def __init__(self, source_interaction=None):
        super().__init__()
        self.source_interaction = source_interaction

    async def on_submit(self, interaction: discord.Interaction):
        db = get_database()
        try:
            urls = await validate_monitor_urls(
                self.status_url.value, self.update_url.value
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        except Exception as exc:
            logger.error(
                "Falha ao validar URLs de monitoramento (%s).", type(exc).__name__
            )
            await interaction.response.send_message(
                "Não foi possível validar as URLs. Tente novamente.", ephemeral=True
            )
            return

        message = (
            "URLs preenchidas salvas."
            if urls
            else "Nenhuma alteração; campos vazios mantêm as URLs atuais."
        )
        if await save_modal_settings(
            interaction,
            db,
            urls,
            failure_message="Não foi possível salvar as URLs. Tente novamente.",
        ):
            await send_temporary_confirmation(interaction, message, delay=10)


class StatusMessageModal(AdminModal, title="Recuperar Mensagem de Status"):
    message_id = TextInput(
        label="ID da mensagem de status",
        placeholder="Cole aqui o ID da mensagem fixa",
        required=True,
        min_length=17,
        max_length=25,
    )

    async def on_submit(self, interaction: discord.Interaction):
        status_cog = cast(
            StatusCog | None,
            cast(commands.Bot, interaction.client).get_cog("StatusCog"),
        )
        if not status_cog:
            await interaction.response.send_message(
                "Não encontrei a cog de status carregada.", ephemeral=True
            )
            return

        try:
            message_id = int(self.message_id.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "O ID da mensagem precisa ser numérico.", ephemeral=True
            )
            return

        chan_id = await get_config(status_cog.db, "status_channel_id")
        if not chan_id:
            await interaction.response.send_message(
                "Configure primeiro o canal de status no painel.", ephemeral=True
            )
            return

        channel = interaction.client.get_channel(chan_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Não consegui encontrar o canal de status configurado.", ephemeral=True
            )
            return

        await restore_status_message(interaction, status_cog, channel, message_id)


async def open_notification_settings(interaction, db):
    settings = await get_config_values(
        db,
        (
            "status_role_id",
            "update_role_id",
            "status_ping_enabled",
            "update_ping_enabled",
        ),
        {"status_ping_enabled": False, "update_ping_enabled": False},
    )
    status_role_id, update_role_id = (
        settings["status_role_id"],
        settings["update_role_id"],
    )
    status_ping_enabled = bool(settings["status_ping_enabled"])
    update_ping_enabled = bool(settings["update_ping_enabled"])
    guild = getattr(interaction, "guild", None)
    if guild:
        if status_role_id and guild.get_role(int(status_role_id)) is None:
            status_role_id = None
        if update_role_id and guild.get_role(int(update_role_id)) is None:
            update_role_id = None
    await interaction.response.send_modal(
        NotificationSettingsModal(
            db,
            status_role_id=status_role_id,
            update_role_id=update_role_id,
            status_ping_enabled=status_ping_enabled,
            update_ping_enabled=update_ping_enabled,
        )
    )


async def open_channel_settings(interaction, db):
    settings = await get_config_values(db, ("status_channel_id", "update_channel_id"))
    status_channel_id, update_channel_id = (
        settings["status_channel_id"],
        settings["update_channel_id"],
    )
    guild = getattr(interaction, "guild", None)
    if guild:
        if status_channel_id and guild.get_channel(int(status_channel_id)) is None:
            status_channel_id = None
        if update_channel_id and guild.get_channel(int(update_channel_id)) is None:
            update_channel_id = None
    await interaction.response.send_modal(
        ChannelSettingsModal(
            db,
            status_channel_id,
            update_channel_id,
        )
    )


async def open_service_settings(interaction, db):
    settings = await get_config_values(
        db,
        (
            "status_monitor_enabled",
            "announcements_enabled",
            "status_old_messages_cleanup_enabled",
        ),
        {
            "status_monitor_enabled": True,
            "announcements_enabled": True,
            "status_old_messages_cleanup_enabled": False,
        },
    )
    status_enabled = bool(settings["status_monitor_enabled"])
    announcements_enabled = bool(settings["announcements_enabled"])
    status_cleanup_enabled = bool(settings["status_old_messages_cleanup_enabled"])
    await interaction.response.send_modal(
        ServiceSettingsModal(
            db,
            status_enabled,
            announcements_enabled,
            status_cleanup_enabled,
        )
    )


class NotificationSettingsModal(AdminModal, title="Configurar notificações"):
    def __init__(
        self,
        db,
        status_role_id=None,
        update_role_id=None,
        status_ping_enabled=False,
        update_ping_enabled=False,
    ):
        super().__init__()
        self.db = db

        self.status_role_select = discord.ui.RoleSelect(
            placeholder="Cargo de Status",
            min_values=0,
            max_values=1,
            required=False,
            default_values=select_default_values(
                status_role_id, discord.SelectDefaultValueType.role
            ),
        )
        self.update_role_select = discord.ui.RoleSelect(
            placeholder="Cargo de Anúncios",
            min_values=0,
            max_values=1,
            required=False,
            default_values=select_default_values(
                update_role_id, discord.SelectDefaultValueType.role
            ),
        )
        self.status_ping_select = toggle_select(
            "Ping de Status", status_ping_enabled, required=False
        )
        self.update_ping_select = toggle_select(
            "Ping de Anúncios", update_ping_enabled, required=False
        )

        self.add_item(
            discord.ui.Label(
                text="Cargo de Status",
                description="Cargo mencionado quando o status mudar.",
                component=self.status_role_select,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Cargo de Anúncios",
                description="Cargo mencionado quando houver um novo anúncio.",
                component=self.update_role_select,
            )
        )
        self.add_item(
            discord.ui.Label(text="Ping de Status", component=self.status_ping_select)
        )
        self.add_item(
            discord.ui.Label(text="Ping de Anúncios", component=self.update_ping_select)
        )

    async def on_submit(self, interaction: discord.Interaction):
        status_role = self.status_role_select.values
        update_role = self.update_role_select.values
        values = {
            "status_role_id": status_role[0].id if status_role else "",
            "update_role_id": update_role[0].id if update_role else "",
            "status_ping_enabled": bool(self.status_ping_select.values)
            and self.status_ping_select.values[0] == "true",
            "update_ping_enabled": bool(self.update_ping_select.values)
            and self.update_ping_select.values[0] == "true",
        }
        await save_modal_settings(
            interaction,
            self.db,
            values,
            failure_message="Não foi possível salvar as notificações. Tente novamente.",
        )


class ChannelSettingsModal(AdminModal, title="Configurar canais"):
    def __init__(self, db, status_channel_id=None, update_channel_id=None):
        super().__init__()
        self.db = db

        channel_types = [discord.ChannelType.text, discord.ChannelType.news]
        self.status_channel_select = discord.ui.ChannelSelect(
            placeholder="Canal de Status",
            channel_types=channel_types,
            min_values=0,
            max_values=1,
            required=False,
            default_values=select_default_values(
                status_channel_id, discord.SelectDefaultValueType.channel
            ),
        )
        self.update_channel_select = discord.ui.ChannelSelect(
            placeholder="Canal de Anúncios",
            channel_types=channel_types,
            min_values=0,
            max_values=1,
            required=False,
            default_values=select_default_values(
                update_channel_id, discord.SelectDefaultValueType.channel
            ),
        )
        self.add_item(
            discord.ui.Label(
                text="Canal de Status",
                description="Opcional; limpe para remover o canal.",
                component=self.status_channel_select,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Canal de Anúncios",
                description="Opcional; limpe para remover o canal.",
                component=self.update_channel_select,
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        status = self.status_channel_select.values
        update = self.update_channel_select.values
        await save_modal_settings(
            interaction,
            self.db,
            {
                "status_channel_id": status[0].id if status else None,
                "update_channel_id": update[0].id if update else None,
            },
            failure_message="Não foi possível salvar os canais. Tente novamente.",
        )


class ServiceSettingsModal(AdminModal, title="Serviços automáticos"):
    def __init__(
        self,
        db,
        status_enabled=True,
        announcements_enabled=True,
        status_cleanup_enabled=False,
    ):
        super().__init__()
        self.db = db
        self.status_select = toggle_select("Monitor de status", status_enabled)
        self.announcements_select = toggle_select(
            "Anúncios automáticos", announcements_enabled
        )
        self.status_cleanup_select = toggle_select(
            "Limpeza de status antigo", status_cleanup_enabled
        )
        self.add_item(
            discord.ui.Label(text="Monitor de status", component=self.status_select)
        )
        self.add_item(
            discord.ui.Label(
                text="Anúncios automáticos", component=self.announcements_select
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Limpeza de status antigo",
                description="Apaga apenas painéis antigos do bot e preserva o atual.",
                component=self.status_cleanup_select,
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        await save_modal_settings(
            interaction,
            self.db,
            {
                "status_monitor_enabled": self.status_select.values[0] == "true",
                "announcements_enabled": self.announcements_select.values[0] == "true",
                "status_old_messages_cleanup_enabled": (
                    self.status_cleanup_select.values[0] == "true"
                ),
            },
            failure_message="Não foi possível salvar os serviços. Tente novamente.",
        )
