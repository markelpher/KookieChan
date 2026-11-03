"""Cog e interface interativa de ajuda do bot."""

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select

from src.core.utils import get_config
from src.database.database import get_database
from src.ui.components import Panel, PanelContent

BLUE_COLOR = 0x3498DB


class HelpSelect(Select):
    def __init__(self, bot, update_url):
        self.bot = bot
        self.update_url = update_url
        options = [
            discord.SelectOption(
                label="Início", description="Página inicial da ajuda", value="home"
            ),
            discord.SelectOption(
                label="Monitoramento", description="Status e latência", value="monitor"
            ),
            discord.SelectOption(
                label="Conteúdo", description="Histórico e anúncios", value="content"
            ),
            discord.SelectOption(
                label="Links", description="Links úteis do projeto", value="links"
            ),
        ]
        super().__init__(placeholder="Escolha uma categoria...", options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        content = self.get_content(value)
        view = self.view
        if content is not None and isinstance(view, HelpView):
            await interaction.response.edit_message(view=view.set_content(content))

    def get_content(self, category: str):
        if category == "home":
            return PanelContent(
                title="Olá! Eu sou a Kookie Chan",
                description=(
                    "Boas-vindas ao meu menu de ajuda! Eu monitoro o status do [Kookie](https://kookie.app) e "
                    "mantenho você informado sobre cada novo anúncio.\n\n"
                    "Use o menu abaixo para navegar entre as categorias."
                ),
                accent_color=BLUE_COLOR,
                thumbnail=self.bot.user.display_avatar.url,
            )

        elif category == "monitor":
            return PanelContent(
                title="Monitoramento & Status",
                description="Comandos para verificar o status do Kookie e do bot.",
                accent_color=BLUE_COLOR,
                sections=(
                    (
                        "/status",
                        "Exibe o status atual do Kookie (online/offline) e o tempo contínuo online.",
                    ),
                    ("/ping", "Verifica a latência atual entre mim e o Discord."),
                ),
            )

        elif category == "content":
            return PanelContent(
                title="Conteúdo & Histórico",
                description="Acesse o que aconteceu recentemente ou veja as novidades.",
                accent_color=BLUE_COLOR,
                sections=(
                    (
                        "/historico",
                        "Consulto o histórico recente de status ou anúncios salvos no banco de dados.",
                    ),
                    (
                        "/update",
                        "Busco e exibo a atualização ou o anúncio mais recente do Kookie.",
                    ),
                ),
            )

        elif category == "links":
            return PanelContent(
                title="Links Úteis",
                accent_color=BLUE_COLOR,
                description=(
                    f"• [Kookie](https://kookie.app)\n"
                    f"• [Página de anúncios do Kookie]({self.update_url})\n"
                    "• [Repositório GitHub](https://github.com/markelpher/KookieChan)\n"
                    "• [Docker Hub](https://hub.docker.com/r/markelpher/kookiechan)"
                ),
            )


class HelpView(Panel):
    def __init__(self, bot, update_url):
        super().__init__(timeout=120)
        self.message: discord.Message | None = None
        self.menu = HelpSelect(bot, update_url)
        self.add_item(self.menu)

    async def on_timeout(self):
        self.menu.disabled = True
        if hasattr(self, "message") and self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="ajuda", description="Abre o menu interativo de ajuda da Kookie Chan"
    )
    async def ajuda(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        db = get_database()
        update_url = await get_config(
            db, "kookie_update_url", "https://kookie.app/announcements"
        )
        view = HelpView(self.bot, update_url)
        home_content = view.menu.get_content("home")
        if home_content is None:
            raise RuntimeError("Conteúdo inicial da ajuda indisponível.")

        view.message = await interaction.followup.send(
            view=view.set_content(home_content), ephemeral=True, wait=True
        )


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
