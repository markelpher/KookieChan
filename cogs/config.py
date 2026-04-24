import discord
from discord.ext import commands
from discord import app_commands, Embed
from discord.ui import View, Select, Button, Modal, TextInput
from datetime import datetime
from database.mongo import get_database
from utils import BR_TZ, parse_brazilian_date, get_config, set_config

# ------------------------
# HELPERS PARA REUSO DE UI
# ------------------------

async def get_dashboard_embed(bot, db):
    # Busca configurações atuais para o resumo
    status_channel_id = await get_config(db, "status_channel_id")
    update_channel_id = await get_config(db, "update_channel_id")
    
    status_ping = await get_config(db, "status_ping_enabled", False)
    update_ping = await get_config(db, "update_ping_enabled", False)
    status_role_id = await get_config(db, "status_role_id")
    update_role_id = await get_config(db, "update_role_id")
    
    st_chan = f"<#{status_channel_id}>" if status_channel_id else "Não definido"
    up_chan = f"<#{update_channel_id}>" if update_channel_id else "Não definido"
    
    st_ping_status = "✅ Ativado" if status_ping else "❌ Desativado"
    up_ping_status = "✅ Ativado" if update_ping else "❌ Desativado"
    
    st_role_mention = f"<@&{status_role_id}>" if status_role_id else "Não definido"
    up_role_mention = f"<@&{update_role_id}>" if update_role_id else "Não definido"

    embed = Embed(
        title="Dashboard Administrativa",
        description=(
            "Bem-vindo ao centro de controle!\n"
            "Gerencie canais, URLs e notificações do bot abaixo."
        ),
        color=0x2ecc71
    )
    embed.add_field(name="Monitoramento", value=f"Canal Status: {st_chan}\nCanal Update: {up_chan}", inline=False)
    embed.add_field(name="Pings de Status", value=f"Status: {st_ping_status}\nCargo: {st_role_mention}", inline=True)
    embed.add_field(name="Pings de Update", value=f"Status: {up_ping_status}\nCargo: {up_role_mention}", inline=True)
    embed.set_footer(text="Apenas administradores podem ver este painel.")
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    return embed


async def get_notifications_embed(bot, db):
    embed = await get_dashboard_embed(bot, db)
    embed.title = "Configurações de Notificações"
    embed.description = "Escolha os cargos e ligue ou desligue os pings de status e update."
    return embed

# -------------------------
# MODAIS (Janelas de Texto)
# -------------------------

class DataModal(Modal, title="Métricas de Tempo"):
    data_input = TextInput(
        label="Data Retroativa (DD/MM/YYYY HH:MM)",
        placeholder="Ex: 28/08/2025 15:30",
        required=True,
        min_length=16,
        max_length=16
    )

    async def on_submit(self, interaction: discord.Interaction):
        status_cog = interaction.client.get_cog("StatusCog")
        try:
            val = self.data_input.value
            dt = parse_brazilian_date(val)
            now = datetime.now(BR_TZ)
            delta = (now - dt).total_seconds()
            if delta < 0:
                return await interaction.response.send_message("A data não pode ser no futuro!", ephemeral=True)
            
            is_online = status_cog.state.get("online", False)
            status_cog.state["continuous_online"] = delta if is_online else 0
            status_cog.state["continuous_offline"] = delta if not is_online else 0
            status_cog.state["last_status_change"] = now.timestamp()
            await status_cog.save_state()
            await interaction.response.send_message(f"Tempo sincronizado para: **{val}**", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Erro: {e}", ephemeral=True)

class UrlModal(Modal, title="URLs do Monitor"):
    status_url = TextInput(label="URL de Status", placeholder="https://...", required=False)
    update_url = TextInput(label="URL de Update", placeholder="https://...", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        db = get_database()
        logs = []
        if self.status_url.value:
            await set_config(db, "kookie_status_url", self.status_url.value)
            logs.append(f"URL Status: `{self.status_url.value}`")
        if self.update_url.value:
            await set_config(db, "kookie_update_url", self.update_url.value)
            logs.append(f"URL Update: `{self.update_url.value}`")
        
        await interaction.response.send_message("\n".join(logs) if logs else "Nenhuma alteração.", ephemeral=True)


class StatusMessageModal(Modal, title="Recuperar Mensagem de Status"):
    message_id = TextInput(
        label="ID da mensagem antiga",
        placeholder="Cole aqui o ID da mensagem fixa antiga",
        required=True,
        min_length=17,
        max_length=25
    )

    async def on_submit(self, interaction: discord.Interaction):
        status_cog = interaction.client.get_cog("StatusCog")
        if not status_cog:
            await interaction.response.send_message("Não encontrei a cog de status carregada.", ephemeral=True)
            return

        try:
            message_id = int(self.message_id.value.strip())
        except ValueError:
            await interaction.response.send_message("O ID da mensagem precisa ser numérico.", ephemeral=True)
            return

        chan_id = await get_config(status_cog.db, "status_channel_id")
        if not chan_id:
            await interaction.response.send_message("Configure primeiro o canal de status no painel.", ephemeral=True)
            return

        channel = interaction.client.get_channel(chan_id)
        if not channel:
            await interaction.response.send_message("Não consegui encontrar o canal de status configurado.", ephemeral=True)
            return

        try:
            old_message = await channel.fetch_message(message_id)
        except discord.NotFound:
            await interaction.response.send_message("Não encontrei essa mensagem no canal de status configurado.", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"Falha ao buscar a mensagem: {e}", ephemeral=True)
            return

        previous_id = status_cog.state.get("status_message_id")
        previous_message = None
        if previous_id and previous_id != message_id:
            try:
                previous_message = await channel.fetch_message(previous_id)
            except Exception:
                previous_message = None

        status_cog.state["config"] = {
            "kookie_status_url": await get_config(status_cog.db, "kookie_status_url", status_cog.state.get("config", {}).get("kookie_status_url"))
        }
        status_cog.state["status_message_id"] = message_id
        await status_cog.save_state()

        try:
            await old_message.edit(content=None, embed=status_cog.build_embed(status_cog.state))
            await status_cog.sync_status_pin(channel, old_message)
        except Exception as e:
            await interaction.response.send_message(f"Encontrei a mensagem, mas falhei ao atualizá-la: {e}", ephemeral=True)
            return

        if previous_message and previous_message.id != old_message.id and previous_message.author.id == interaction.client.user.id:
            try:
                await previous_message.delete()
            except Exception:
                pass

        await interaction.response.send_message(
            f"Mensagem de status recuperada com sucesso: [ir para mensagem]({old_message.jump_url})",
            ephemeral=True
        )


# ------------------------------
# VIEWS (Interfaces Interativas)
# ------------------------------

class PagedEntitySelect(Select):
    def __init__(self, parent_view, target: str, kind: str, row: int):
        self.parent_view = parent_view
        self.target = target
        self.kind = kind

        label = "Status" if target == "status" else "Update"
        kind_label = "canal" if kind == "channel" else "cargo"
        super().__init__(
            placeholder=f"Selecionar {kind_label} para {label}",
            min_values=1,
            max_values=1,
            row=row,
            options=[discord.SelectOption(label="Carregando...", value="loading")]
        )

    async def refresh_options(self, entities, selected_id=None):
        current = entities[:25]

        if not current:
            self.disabled = True
            self.options = [discord.SelectOption(label="Nenhuma opção disponível", value="empty")]
            return

        self.disabled = False
        options = []
        for entity in current:
            if self.kind == "channel":
                label = f"#{entity.name}"[:100]
                description = f"ID: {entity.id}"
            else:
                label = entity.name[:100]
                description = f"ID: {entity.id}"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(entity.id),
                    description=description[:100],
                    default=entity.id == selected_id
                )
            )
        self.options = options

    async def callback(self, interaction: discord.Interaction):
        entity_id = int(self.values[0])
        await self.parent_view.apply_selection(interaction, self.kind, self.target, entity_id)


class PagedConfigView(View):
    def __init__(self, bot, db):
        super().__init__(timeout=120)
        self.bot = bot
        self.db = db
        self.channel_cache = []
        self.role_cache = []

    async def fetch_entities(self, guild: discord.Guild | None, kind: str):
        if not guild:
            return []
        if kind == "channel":
            channels = await guild.fetch_channels()
            return sorted(
                [channel for channel in channels if isinstance(channel, discord.TextChannel)],
                key=lambda channel: (
                    channel.category.position if channel.category else -1,
                    channel.position,
                    channel.id
                )
            )
        roles = await guild.fetch_roles()
        return sorted(
            [role for role in roles if role != guild.default_role],
            key=lambda role: (-role.position, role.id)
        )

    async def apply_selection(self, interaction: discord.Interaction, kind: str, target: str, entity_id: int):
        raise NotImplementedError


class ChannelDashboard(PagedConfigView):
    def __init__(self, bot, db):
        super().__init__(bot, db)
        self.status_select = PagedEntitySelect(self, "status", "channel", row=0)
        self.update_select = PagedEntitySelect(self, "update", "channel", row=1)
        self.add_item(self.status_select)
        self.add_item(self.update_select)

    async def refresh(self, guild: discord.Guild | None):
        self.channel_cache = await self.fetch_entities(guild, "channel")
        current_status_id = await get_config(self.db, "status_channel_id")
        current_update_id = await get_config(self.db, "update_channel_id")
        await self.status_select.refresh_options(self.channel_cache, current_status_id)
        await self.update_select.refresh_options(self.channel_cache, current_update_id)

    async def apply_selection(self, interaction: discord.Interaction, kind: str, target: str, entity_id: int):
        config_key = "status_channel_id" if target == "status" else "update_channel_id"
        await set_config(self.db, config_key, entity_id)
        embed = await get_dashboard_embed(self.bot, self.db)
        embed.title = "Configuração de Canais"
        embed.description = "Selecione os canais de postagem para status e update."
        await self.refresh(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Voltar", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_start(self, interaction: discord.Interaction, button: Button):
        embed = await get_dashboard_embed(self.bot, self.db)
        await interaction.response.edit_message(content=None, embed=embed, view=DashboardView(self.bot, self.db))


class NotificationView(PagedConfigView):
    def __init__(self, bot, db):
        super().__init__(bot, db)
        self.status_select = PagedEntitySelect(self, "status", "role", row=0)
        self.update_select = PagedEntitySelect(self, "update", "role", row=1)
        self.add_item(self.status_select)
        self.add_item(self.update_select)

    async def refresh_buttons(self):
        status_enabled = await get_config(self.db, "status_ping_enabled", False)
        update_enabled = await get_config(self.db, "update_ping_enabled", False)
        self.toggle_status.label = "Desligar Ping Status" if status_enabled else "Ligar Ping Status"
        self.toggle_status.style = discord.ButtonStyle.danger if status_enabled else discord.ButtonStyle.success
        self.toggle_update.label = "Desligar Ping Update" if update_enabled else "Ligar Ping Update"
        self.toggle_update.style = discord.ButtonStyle.danger if update_enabled else discord.ButtonStyle.success

    async def refresh(self, guild: discord.Guild | None):
        self.role_cache = await self.fetch_entities(guild, "role")
        current_status_id = await get_config(self.db, "status_role_id")
        current_update_id = await get_config(self.db, "update_role_id")
        await self.status_select.refresh_options(self.role_cache, current_status_id)
        await self.update_select.refresh_options(self.role_cache, current_update_id)
        await self.refresh_buttons()

    async def apply_selection(self, interaction: discord.Interaction, kind: str, target: str, entity_id: int):
        config_key = "status_role_id" if target == "status" else "update_role_id"
        await set_config(self.db, config_key, entity_id)
        embed = await get_notifications_embed(self.bot, self.db)
        await self.refresh(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Ligar Ping Status", style=discord.ButtonStyle.success, row=2)
    async def toggle_status(self, interaction: discord.Interaction, button: Button):
        current = await get_config(self.db, "status_ping_enabled", False)
        await set_config(self.db, "status_ping_enabled", not current)
        embed = await get_notifications_embed(self.bot, self.db)
        await self.refresh(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Ligar Ping Update", style=discord.ButtonStyle.success, row=2)
    async def toggle_update(self, interaction: discord.Interaction, button: Button):
        current = await get_config(self.db, "update_ping_enabled", False)
        await set_config(self.db, "update_ping_enabled", not current)
        embed = await get_notifications_embed(self.bot, self.db)
        await self.refresh(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Voltar", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: Button):
        embed = await get_dashboard_embed(self.bot, self.db)
        await interaction.response.edit_message(content=None, embed=embed, view=DashboardView(self.bot, self.db))

# -----------------------------------
# DASHBOARD PRINCIPAL (DashboardView)
# -----------------------------------

class DashboardView(View):
    def __init__(self, bot, db):
        super().__init__(timeout=120)
        self.bot = bot
        self.db = db

    @discord.ui.select(
        placeholder="Escolha uma categoria para configurar...",
        options=[
            discord.SelectOption(label="Canais", description="Configura onde o bot posta", value="canais"),
            discord.SelectOption(label="URLs", description="Configura os sites monitorados", value="urls"),
            discord.SelectOption(label="Tempo & Dados", description="Sincroniza uptime ou reseta dados", value="tempo"),
            discord.SelectOption(label="Notificações", description="Configura pings e cargos", value="pings"),
            discord.SelectOption(label="Mensagem Fixa", description="Recupera a mensagem de status por ID", value="mensagem_fixa")
        ]
    )
    async def select_category(self, interaction: discord.Interaction, select: Select):
        cat = select.values[0]

        if cat == "canais":
            embed = await get_dashboard_embed(self.bot, self.db)
            embed.title = "Configuração de Canais"
            embed.description = "Selecione os canais de postagem para status e update."
            view = ChannelDashboard(self.bot, self.db)
            await view.refresh(interaction.guild)
            await interaction.response.edit_message(embed=embed, view=view)
        
        elif cat == "urls":
            await interaction.response.send_modal(UrlModal())
        
        elif cat == "tempo":
            view = View()
            async def reset_btn(inter):
                status_cog = self.bot.get_cog("StatusCog")
                status_cog.state.update({
                    "continuous_online": 0, "continuous_offline": 0, "total_online": 0, "total_offline": 0, "downtimes_count": 0,
                    "last_status_change": datetime.now(BR_TZ).timestamp()
                })
                await status_cog.save_state()
                await inter.response.send_message("Banco de dados e status limpos!", ephemeral=True)

            async def sync_btn(inter):
                await inter.response.send_modal(DataModal())

            async def back_btn(inter):
                embed = await get_dashboard_embed(self.bot, self.db)
                await inter.response.edit_message(content=None, embed=embed, view=DashboardView(self.bot, self.db))

            b1 = Button(label="Sincronizar Data", style=discord.ButtonStyle.primary)
            b1.callback = sync_btn
            b2 = Button(label="Zerar Tudo", style=discord.ButtonStyle.danger)
            b2.callback = reset_btn
            b3 = Button(label="Voltar", style=discord.ButtonStyle.secondary)
            b3.callback = back_btn
            
            view.add_item(b1)
            view.add_item(b2)
            view.add_item(b3)
            await interaction.response.edit_message(content="Controle de Métricas:", embed=None, view=view)

        elif cat == "pings":
            embed = await get_notifications_embed(self.bot, self.db)
            view = NotificationView(self.bot, self.db)
            await view.refresh(interaction.guild)
            await interaction.response.edit_message(embed=embed, view=view)

        elif cat == "mensagem_fixa":
            await interaction.response.send_modal(StatusMessageModal())


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()

    @app_commands.command(name="config", description="Abre o painel de configurações")
    @app_commands.default_permissions(administrator=True)
    async def config_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = await get_dashboard_embed(self.bot, self.db)
        view = DashboardView(self.bot, self.db)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
