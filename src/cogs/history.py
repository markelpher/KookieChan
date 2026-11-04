"""Cog que apresenta o histórico de status do Kookie."""

from datetime import datetime

import discord
from discord import Interaction, app_commands
from discord.ext import commands
from discord.ui import Button

from src.announcements.types import DisplayAnnouncement
from src.core.utils import announcement_date, discord_timestamp
from src.database.announcement_repository import AnnouncementRepository
from src.database.database import get_database
from src.monitoring.types import StatusLogRecord
from src.ui.components import Panel, PanelContent

HISTORY_ITEMS_LIMIT = 20


class HistoryView(Panel):
    def __init__(self, ctx, pages):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages
        self.index = 0
        self.message = None

        self.prev_button = Button(label="⬅️ Anterior", style=discord.ButtonStyle.primary)
        self.next_button = Button(label="Próximo ➡️", style=discord.ButtonStyle.primary)
        self.prev_button.callback = self.prev_page
        self.next_button.callback = self.next_page
        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.pages) - 1

    async def _change_page(self, interaction: Interaction, offset: int):
        if interaction.user != self.ctx.user:
            return await interaction.response.send_message(
                "❌ Apenas quem usou o comando pode interagir.", ephemeral=True
            )
        self.index += offset
        self.update_buttons()
        await interaction.response.edit_message(
            view=self.set_content(self.pages[self.index])
        )

    async def prev_page(self, interaction: Interaction):
        await self._change_page(interaction, -1)

    async def next_page(self, interaction: Interaction):
        await self._change_page(interaction, 1)


class HistoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()
        self.announcements = AnnouncementRepository(self.db)

    def build_status_content(self, log: StatusLogRecord) -> PanelContent:
        ts = datetime.fromisoformat(log["checked_at"].replace("Z", "+00:00"))
        return PanelContent(
            title="📊 Histórico de Status do Kookie",
            sections=(
                ("Status", "ONLINE 🟢" if log["online"] else "OFFLINE 🔴"),
                ("Código HTTP", str(log["http_code"])),
                ("Tempo de resposta", f"{log['response_time']} ms"),
            ),
            accent_color=0x00FF00 if log["online"] else 0xFF0000,
            footer=f"Verificado em: {discord_timestamp(ts)}",
        )

    def build_update_content(self, update: DisplayAnnouncement) -> PanelContent:
        date = update["date"]
        dt = (
            date
            if isinstance(date, datetime)
            else datetime.fromisoformat(date.replace("Z", "+00:00"))
        )
        return PanelContent(
            title=f"📢 {update['title']}",
            description=update["description"],
            accent_color=0xFFD700,
            footer=f"Data de referência: {announcement_date(dt)}",
        )

    async def load_history_pages(self, history_type):
        if history_type == "status":
            logs = await self.db.list_status(HISTORY_ITEMS_LIMIT) or []
            pages = [self.build_status_content(log) for log in logs]
            return pages, "Nenhum histórico de status encontrado."

        logs = await self.announcements.list_updates(HISTORY_ITEMS_LIMIT) or []
        pages = [self.build_update_content(log) for log in logs]
        return pages, "Nenhum histórico de anúncios encontrado."

    @commands.hybrid_command(
        name="historico",
        description="Mostra o histórico de status ou anúncios do Kookie",
    )
    @app_commands.choices(
        tipo=[
            app_commands.Choice(name="Status", value="status"),
            app_commands.Choice(name="Anúncios", value="update"),
        ]
    )
    async def historico(self, ctx, tipo: app_commands.Choice[str]):
        if ctx.interaction:
            await ctx.interaction.response.defer(ephemeral=True)

        pages, empty_message = await self.load_history_pages(tipo.value)
        if not pages:
            if ctx.interaction:
                await ctx.interaction.followup.send(empty_message, ephemeral=True)
            else:
                await ctx.send(empty_message)
            return

        view = HistoryView(ctx, pages)
        if ctx.interaction:
            await ctx.interaction.followup.send(
                view=view.set_content(pages[0]), ephemeral=True
            )
        else:
            await ctx.send(view=view.set_content(pages[0]))


async def setup(bot):
    await bot.add_cog(HistoryCog(bot))
