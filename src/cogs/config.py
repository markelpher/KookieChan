"""Cog que registra os comandos de configuração administrativa."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from src.configuration.forms import (
    ChannelSettingsModal,
    DataModal,
    NotificationSettingsModal,
    ServiceSettingsModal,
    StatusMessageModal,
    UrlModal,
    open_channel_settings,
    open_notification_settings,
    open_service_settings,
    restore_status_message,
    select_default_values,
    toggle_select,
)
from src.configuration.support import (
    DEFAULT_DASHBOARD_SETTINGS,
    AdminModal,
    AdminPanel,
    apply_data_action,
    build_dashboard_content,
    collect_monitor_urls,
    delete_previous_status_message,
    get_config_values,
    get_dashboard_content,
    is_authorized_admin,
    require_admin,
    send_temporary_confirmation,
    validate_monitor_url,
    validate_monitor_url_destination,
    validate_monitor_urls,
)
from src.configuration.views import DashboardView, save_modal_settings, show_dashboard
from src.core.background import cancel_supervised_tasks
from src.database.database import get_database

logger = logging.getLogger("src.cogs.config")

__all__ = [
    "DEFAULT_DASHBOARD_SETTINGS",
    "AdminModal",
    "AdminPanel",
    "ChannelSettingsModal",
    "ConfigCog",
    "DashboardView",
    "DataModal",
    "NotificationSettingsModal",
    "ServiceSettingsModal",
    "StatusMessageModal",
    "UrlModal",
    "apply_data_action",
    "build_dashboard_content",
    "collect_monitor_urls",
    "delete_previous_status_message",
    "get_config_values",
    "get_dashboard_content",
    "is_authorized_admin",
    "open_channel_settings",
    "open_notification_settings",
    "open_service_settings",
    "require_admin",
    "restore_status_message",
    "save_modal_settings",
    "select_default_values",
    "send_temporary_confirmation",
    "setup",
    "show_dashboard",
    "toggle_select",
    "validate_monitor_url",
    "validate_monitor_url_destination",
    "validate_monitor_urls",
]


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()

    async def cog_unload(self):
        await cancel_supervised_tasks(self.bot, owner="config")

    @app_commands.command(
        name="configurações", description="Abre o painel de configurações"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.check(is_authorized_admin)
    async def config_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        content = await get_dashboard_content(self.db)
        view = DashboardView(self.bot, self.db)
        await interaction.followup.send(view=view.set_content(content), ephemeral=True)


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
