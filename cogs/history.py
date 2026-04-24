import discord
from discord.ext import commands
from discord import Embed, app_commands, Interaction
from discord.ui import View, Button
import os
from datetime import datetime
from database.mongo import get_database
from utils import format_datetime_br

COLL_STATUS_LOGS = os.getenv("MONGO_STATUS_LOGS_COLLECTION", "status_logs")
COLL_UPDATE = os.getenv("MONGO_UPDATE_COLLECTION", "update")


class HistoryView(View):
    def __init__(self, ctx, embeds):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.embeds = embeds
        self.index = 0
        self.message = None

        # Botões
        self.prev_button = Button(label="⬅️ Anterior", style=discord.ButtonStyle.primary)
        self.next_button = Button(label="Próximo ➡️", style=discord.ButtonStyle.primary)
        self.prev_button.callback = self.prev_page
        self.next_button.callback = self.next_page
        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.embeds) - 1

    async def prev_page(self, interaction: Interaction):
        if interaction.user != self.ctx.user:
            return await interaction.response.send_message(
                "❌ Apenas quem usou o comando pode interagir.", ephemeral=True
            )
        self.index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    async def next_page(self, interaction: Interaction):
        if interaction.user != self.ctx.user:
            return await interaction.response.send_message(
                "❌ Apenas quem usou o comando pode interagir.", ephemeral=True
            )
        self.index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)


class HistoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        db = get_database()
        self.db_status = db[COLL_STATUS_LOGS]
        self.db_update = db[COLL_UPDATE]

    def build_status_embed(self, log):
        # Converte timestamp para datetime se necessário
        ts = datetime.utcfromtimestamp(log["timestamp"]) if isinstance(log["timestamp"], (int, float)) else log["timestamp"]
        embed = Embed(
            title="📊 Histórico de Status do Kookie",
            color=0x00FF00 if log["online"] else 0xFF0000,
            timestamp=ts
        )
        embed.add_field(name="Status", value="ONLINE 🟢" if log["online"] else "OFFLINE 🔴")
        embed.add_field(name="Código HTTP", value=str(log["http_code"]))
        embed.add_field(name="Tempo de resposta", value=f"{log['response_time']}ms")
        embed.set_footer(text=f"Verificado em: {format_datetime_br(ts.timestamp())}")
        return embed

    def build_update_embed(self, update):
        # Garante que update['date'] seja datetime
        dt = update["date"] if isinstance(update["date"], datetime) else datetime.utcfromtimestamp(update["date"])
        embed = Embed(
            title=f"📢 {update['title']}",
            description=update["description"],
            color=0xFFD700,
            timestamp=dt
        )
        embed.set_footer(text=f"Atualização em: {format_datetime_br(dt.timestamp())}")
        return embed

    @commands.hybrid_command(
        name="historico",
        description="Mostra o histórico de status ou update do Kookie"
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="status", value="status"),
        app_commands.Choice(name="update", value="update")
    ])
    async def historico(self, ctx, tipo: app_commands.Choice[str]):
        if ctx.interaction:
            await ctx.interaction.response.defer(ephemeral=True)

        if tipo.value == "status":
            cursor = self.db_status.find().sort("timestamp", -1).limit(20)
            logs = await cursor.to_list(length=20)
            if not logs:
                if ctx.interaction:
                    await ctx.interaction.followup.send("Nenhum histórico de status encontrado.", ephemeral=True)
                else:
                    await ctx.send("Nenhum histórico de status encontrado.")
                return
            embeds = [self.build_status_embed(log) for log in logs]

        elif tipo.value == "update":
            cursor = self.db_update.find().sort("timestamp", -1).limit(20)
            logs = await cursor.to_list(length=20)
            if not logs:
                if ctx.interaction:
                    await ctx.interaction.followup.send("Nenhum histórico de update encontrado.", ephemeral=True)
                else:
                    await ctx.send("Nenhum histórico de update encontrado.")
                return
            embeds = [self.build_update_embed(log) for log in logs]

        view = HistoryView(ctx, embeds)
        if ctx.interaction:
            await ctx.interaction.followup.send(embed=embeds[0], view=view, ephemeral=True)
        else:
            await ctx.send(embed=embeds[0], view=view)


async def setup(bot):
    await bot.add_cog(HistoryCog(bot))
