import discord
from discord.ext import commands
from discord import app_commands, Embed
from discord.ui import View, Select
import os

BLUE_COLOR = 0x3498db

class HelpSelect(Select):
    def __init__(self, bot):
        self.bot = bot
        options = [
            discord.SelectOption(label="Início", description="Página inicial da ajuda", value="home"),
            discord.SelectOption(label="Monitoramento", description="Status e latência", value="monitor"),
            discord.SelectOption(label="Conteúdo", description="Histórico e update", value="content"),
            discord.SelectOption(label="Links", description="Links úteis do projeto", value="links")
        ]
        super().__init__(placeholder="Escolha uma categoria...", options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        embed = self.get_embed(value)
        await interaction.response.edit_message(embed=embed, view=self.view)

    def get_embed(self, category: str):
        if category == "home":
            embed = Embed(
                title="Olá! Eu sou a Kookie Chan",
                description=(
                    "Boas vindas ao meu menu de ajuda! Eu monitoro o status do [Kookie](https://kookie.app) e "
                    "mantenho você informado sobre cada novo update.\n\n"
                    "Use o menu abaixo para navegar entre as categorias."
                ),
                color=BLUE_COLOR
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        elif category == "monitor":
            embed = Embed(
                title="Monitoramento & Status",
                description="Comandos para verificar o status do Kookie e do bot.",
                color=BLUE_COLOR
            )
            embed.add_field(name="`/status`", value="Exibe o status atual do Kookie (Online/Offline) e estatísticas de uptime.", inline=False)
            embed.add_field(name="`/ping`", value="Verifica a latência atual entre mim e o Discord.", inline=False)

        elif category == "content":
            embed = Embed(
                title="Conteúdo & Histórico",
                description="Acesse o que aconteceu recentemente ou veja as novidades.",
                color=BLUE_COLOR
            )
            embed.add_field(name="`/historico`", value="Consulto o histórico recente de status ou anúncios salvos no banco de dados.", inline=False)
            embed.add_field(name="`/update`", value="Busco e exibo a atualização ou anúncio mais recente do Kookie.", inline=False)

        elif category == "links":
            embed = Embed(
                title="Links Úteis",
                color=BLUE_COLOR
            )
            status_url = os.getenv("KOOKIE_STATUS_URL", "https://github.com/markelpher/KookieChan")
            update_url = os.getenv("KOOKIE_UPDATE_URL", "#")
            
            embed.description = (
                f"• [Kookie](https://kookie.app)\n"
                f"• [Página de Update do Kookie]({update_url if update_url != '#' else 'https://kookie.app/updates'})\n"
                "• [Repositório GitHub](https://github.com/markelpher/KookieChan)\n"
                "• [Docker Hub](https://hub.docker.com/r/markelpher/kookiechan)"
            )
        return embed

class HelpView(View):
    def __init__(self, bot):
        super().__init__(timeout=120)
        self.add_item(HelpSelect(bot))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, "message") and self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="ajuda",
        description="Abre o menu interativo de ajuda da Kookie Chan"
    )
    async def ajuda(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        view = HelpView(self.bot)
        home_embed = view.children[0].get_embed("home")

        view.message = await interaction.followup.send(
            embed=home_embed,
            view=view,
            ephemeral=True,
            wait=True
        )

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
