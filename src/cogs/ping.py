"""Cog com o comando simples de verificação de resposta do bot."""

import discord
from discord.ext import commands

from src.ui.components import PanelContent, panel


class PingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="ping", description="Mostra a latência do bot")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)

        if latency_ms < 100:
            color = 0x00FF00  # verde
        elif latency_ms < 200:
            color = 0xFFFF00  # amarelo
        else:
            color = 0xFF0000  # vermelho

        now = discord.utils.utcnow()
        content = PanelContent(
            title="🏓 Pong!",
            description=f"Latência atual: **{latency_ms} ms**",
            accent_color=color,
            footer=f"Consultado em <t:{int(now.timestamp())}:F>",
        )

        try:
            await interaction.response.send_message(view=panel(content), ephemeral=True)
        except discord.NotFound:
            return


async def setup(bot):
    await bot.add_cog(PingCog(bot))
