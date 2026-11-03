"""Painel principal e roteamento das categorias de configuração."""

import logging

import discord
from discord.ui import Select

from src.configuration.support import AdminPanel, get_dashboard_content

logger = logging.getLogger("src.cogs.config")


async def show_dashboard(interaction, db):
    content = await get_dashboard_content(db)
    view = DashboardView(interaction.client, db).set_content(content)
    await interaction.response.edit_message(
        view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def save_modal_settings(interaction, db, values, *, failure_message):
    try:
        await db.set_configs(values)
    except Exception as exc:
        logger.error("Falha ao salvar configuração (%s).", type(exc).__name__)
        if not interaction.response.is_done():
            await interaction.response.send_message(failure_message, ephemeral=True)
        return False

    try:
        await show_dashboard(interaction, db)
    except Exception as exc:
        logger.warning(
            "Configuração salva, mas o dashboard não foi atualizado (%s).",
            type(exc).__name__,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "As configurações foram salvas, mas não foi possível atualizar o painel. "
                "Reabra /configurações.",
                ephemeral=True,
            )
        return False
    return True


class DashboardView(AdminPanel):
    def __init__(self, bot, db):
        super().__init__(timeout=120)
        self.bot = bot
        self.db = db

    @discord.ui.select(
        placeholder="Escolha uma categoria para configurar...",
        options=[
            discord.SelectOption(
                label="Canais", description="Configura onde o bot posta", value="canais"
            ),
            discord.SelectOption(
                label="URLs", description="Configura os sites monitorados", value="urls"
            ),
            discord.SelectOption(
                label="Serviços",
                description="Ativa ou pausa status e anúncios",
                value="servicos",
            ),
            discord.SelectOption(
                label="Tempo e dados",
                description="Sincroniza o tempo ou zera as métricas",
                value="tempo",
            ),
            discord.SelectOption(
                label="Notificações",
                description="Configura pings e cargos",
                value="pings",
            ),
            discord.SelectOption(
                label="Mensagem fixada",
                description="Recupera a mensagem de status por ID",
                value="mensagem_fixa",
            ),
        ],
    )
    async def select_category(self, interaction: discord.Interaction, select: Select):
        from src.configuration.forms import (
            DataModal,
            StatusMessageModal,
            UrlModal,
            open_channel_settings,
            open_notification_settings,
            open_service_settings,
        )

        cat = select.values[0]

        if cat == "canais":
            await open_channel_settings(interaction, self.db)

        elif cat == "urls":
            await interaction.response.send_modal(UrlModal(interaction))

        elif cat == "servicos":
            await open_service_settings(interaction, self.db)

        elif cat == "tempo":
            await interaction.response.send_modal(DataModal(self.db))

        elif cat == "pings":
            await open_notification_settings(interaction, self.db)

        elif cat == "mensagem_fixa":
            await interaction.response.send_modal(StatusMessageModal())
