import discord
from discord.ext import commands, tasks
from discord import Embed
from discord import app_commands
import asyncio
import os
from datetime import datetime
from database.mongo import get_database

from utils import get_site_status, ms_to_str, format_datetime_br, BR_TZ, get_config

COLL_STATE = os.getenv("MONGO_STATUS_COLLECTION", "status")
COLL_LOGS = os.getenv("MONGO_STATUS_LOGS_COLLECTION", "status_logs")
COLL_ARCHIVE = os.getenv("MONGO_STATUS_ARCHIVE_COLLECTION", "status_logs_archive")
STATUS_EMBED_TITLE = "Status do Kookie"


class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()
        self.db_state = self.db[COLL_STATE]
        self.db_logs = self.db[COLL_LOGS]
        self.db_archive = self.db[COLL_ARCHIVE]

        self.monitor_started = False
        self.pending_status_ping_task = None

        # Estado base
        self.state = {
            "online": None,
            "last_status_change": None,  # timestamp

            "continuous_online": 0.0,
            "continuous_offline": 0.0,

            "total_online": 0.0,
            "total_offline": 0.0,

            "downtimes_count": 0,

            "last_http_code": None,
            "last_response_time": 0,
            "last_check": None,

            "status_message_id": None
        }

    # -------------------- Persistência --------------------
    async def load_state(self):
        print("🔄 Carregando estado do MongoDB...")
        doc = await self.db_state.find_one({"_id": "kookie"})
        if doc and "state" in doc:
            self.state.update(doc["state"])
            print("✅ Estado carregado:", self.state)
        else:
            await self.db_state.insert_one({"_id": "kookie", "state": self.state})
            print("⚠️ Estado não encontrado. Inicializando novo estado.")
            print("💾 Estado salvo no MongoDB:", self.state)

    async def save_state(self):
        await self.db_state.update_one(
            {"_id": "kookie"},
            {"$set": {"state": self.state}},
            upsert=True
        )
        print("💾 Estado atualizado no MongoDB.")

    # -------------------- Embed --------------------
    def build_embed(self, s, changed=False):
        online = s["online"]
        color = 0x00FF00 if online else 0xFF0000
        icon = "🟢" if online else "🔴"

        url_status = s.get("config", {}).get("kookie_status_url", os.getenv("KOOKIE_STATUS_URL"))
        embed = Embed(
            title=STATUS_EMBED_TITLE,
            url=url_status,
            color=color
        )

        embed.add_field(name="Status atual", value=f"{icon} {'ONLINE' if online else 'OFFLINE'}", inline=True)
        embed.add_field(name="Código HTTP", value=str(s["last_http_code"]), inline=True)
        embed.add_field(name="Tempo de resposta", value=f"{s['last_response_time']}ms", inline=True)
        embed.add_field(
            name="Última verificação",
            value=format_datetime_br(s["last_check"]) if s["last_check"] else "--",
            inline=True
        )

        # Tempo contínuo
        if online:
            embed.add_field(
                name="Tempo contínuo online",
                value=ms_to_str(s["continuous_online"] * 1000),
                inline=True
            )
        else:
            embed.add_field(
                name="Tempo contínuo offline",
                value=ms_to_str(s["continuous_offline"] * 1000),
                inline=True
            )

        embed.add_field(name="Total de quedas", value=str(s["downtimes_count"]), inline=True)

        return embed

    # -------------------- Mensagem fixa --------------------
    async def get_status_message(self, channel_id):
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return None

        msg_id = self.state.get("status_message_id")
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                if (
                    msg.author.id == self.bot.user.id
                    and msg.embeds
                    and (msg.embeds[0].title or "") == STATUS_EMBED_TITLE
                ):
                    return msg
                else:
                    self.state["status_message_id"] = None
                    await self.save_state()
            except discord.NotFound:
                self.state["status_message_id"] = None
                await self.save_state()
            except Exception:
                pass

        # Procurar manualmente nas últimas 200 mensagens
        try:
            async for msg in channel.history(limit=200):
                if msg.author.id == self.bot.user.id and msg.embeds:
                    e = msg.embeds[0]
                    if (e.title or "") == STATUS_EMBED_TITLE:
                        self.state["status_message_id"] = msg.id
                        await self.save_state()
                        print("🔁 Mensagem de status recuperada automaticamente (id salvo).")
                        return msg
        except Exception as e:
            print("⚠️ Erro ao procurar mensagem no canal:", e)

        return None

    async def delete_pin_notification(self, channel, pinned_message_id=None):
        try:
            async for msg in channel.history(limit=25):
                if msg.type != discord.MessageType.pins_add:
                    continue
                if msg.author.id != self.bot.user.id:
                    continue
                await msg.delete()
        except Exception as e:
            print("⚠️ Falha ao apagar notificação de mensagem fixada:", e)

    async def sync_status_pin(self, channel, message):
        if not channel or not message:
            return

        try:
            pinned_messages = await channel.pins()
        except Exception as e:
            print("⚠️ Falha ao carregar mensagens fixadas:", e)
            pinned_messages = []

        already_pinned = False
        for pinned in pinned_messages:
            if pinned.id == message.id:
                already_pinned = True
                continue
            if pinned.author.id != self.bot.user.id:
                continue

            try:
                await pinned.unpin(reason="Substituindo mensagem fixa de status")
            except Exception as e:
                print("⚠️ Falha ao desafixar mensagem antiga de status:", e)

        if already_pinned:
            return

        try:
            await message.pin(reason="Mensagem fixa de status do Kookie")
            await self.delete_pin_notification(channel, message.id)
        except discord.HTTPException as e:
            # Ignora erro de mensagem já fixada e segue o fluxo.
            if getattr(e, "code", None) != 30003:
                print("⚠️ Falha ao fixar mensagem de status:", e)
        except Exception as e:
            print("⚠️ Falha ao fixar mensagem de status:", e)

    async def send_status_ping_notification(
        self,
        channel,
        message,
        role_id,
        expected_online,
        expected_change_ts,
        validation_delay=8,
        delete_delay=5
    ):
        if not channel or not role_id:
            return

        try:
            await asyncio.sleep(validation_delay)

            if self.state.get("online") != expected_online:
                return
            if self.state.get("last_status_change") != expected_change_ts:
                return

            status_text = "ONLINE" if expected_online else "OFFLINE"
            sent = await channel.send(content=f"<@&{role_id}> Status do Kookie mudou para {status_text}.")

            await asyncio.sleep(delete_delay)
            await sent.delete()

            if self.state.get("online") != expected_online:
                return
            if self.state.get("last_status_change") != expected_change_ts:
                return

            refreshed_message = message
            if message:
                try:
                    refreshed_message = await channel.fetch_message(message.id)
                except Exception:
                    refreshed_message = message

            if refreshed_message:
                try:
                    await refreshed_message.edit(
                        content=f"<@&{role_id}>",
                        embed=self.build_embed(self.state)
                    )
                    await self.sync_status_pin(channel, refreshed_message)
                except Exception as e:
                    print("⚠️ Falha ao aplicar menção visual na mensagem fixa:", e)
        except asyncio.CancelledError:
            return
        except Exception as e:
            print("⚠️ Falha ao enviar/apagar notificação de ping de status:", e)

    # -------------------- Atualização de estado --------------------
    async def update_state(self, st):
        now_dt = datetime.now(BR_TZ)
        now_ts = now_dt.timestamp()

        if st is None:
            st = {"online": False, "http_code": 0, "response_time": 0}

        prev_online = self.state["online"]
        status_changed = prev_online is not None and prev_online != st["online"]

        if self.state["last_status_change"] is None:
            self.state["last_status_change"] = now_ts

        delta = now_ts - self.state["last_status_change"]

        if status_changed:
            if prev_online:
                self.state["total_online"] = self.state["continuous_online"] + delta
            else:
                self.state["total_offline"] = self.state["continuous_offline"] + delta

            self.state["continuous_online"] = 0
            self.state["continuous_offline"] = 0

            if prev_online and not st["online"]:
                self.state["downtimes_count"] += 1
        else:
            if st["online"]:
                self.state["continuous_online"] += delta
            else:
                self.state["continuous_offline"] += delta

        self.state["online"] = st["online"]
        self.state["last_http_code"] = st["http_code"]
        self.state["last_response_time"] = st["response_time"]
        self.state["last_check"] = now_dt
        self.state["last_status_change"] = now_ts

        await self.save_state()

        # -------------------- LOG DETALHADO --------------------
        status_text = "ONLINE" if self.state["online"] else "OFFLINE"
        cont_time = self.state["continuous_online"] if self.state["online"] else self.state["continuous_offline"]
        total_time = self.state["total_online"] if self.state["online"] else self.state["total_offline"]

        print(f"⏱️ [{now_dt.strftime('%d/%m/%Y %H:%M:%S')}] Status: {status_text}")
        print(f"   Código HTTP: {self.state['last_http_code']}, Tempo de resposta: {self.state['last_response_time']}ms")
        print(f"   Tempo contínuo {'online' if self.state['online'] else 'offline'}: {ms_to_str(cont_time*1000)}")
        print(f"   Tempo total {'online' if self.state['online'] else 'offline'}: {ms_to_str(total_time*1000)}")
        print(f"   Total de quedas: {self.state['downtimes_count']}")

        # Configurações dinâmicas
        chan_id = await get_config(self.db, "status_channel_id", int(os.getenv("STATUS_CHANNEL_ID")))
        self.state["config"] = {"kookie_status_url": await get_config(self.db, "kookie_status_url", os.getenv("KOOKIE_STATUS_URL"))}
        
        # Atualiza embed e envia ping se necessário
        msg = await self.get_status_message(chan_id)
        channel = self.bot.get_channel(chan_id)
        embed = self.build_embed(self.state)

        role_id = None
        status_ping_enabled = await get_config(self.db, "status_ping_enabled", False)
        if status_changed:
            role_id = await get_config(self.db, "status_role_id") if status_ping_enabled else None
            if self.pending_status_ping_task and not self.pending_status_ping_task.done():
                self.pending_status_ping_task.cancel()

        current_content = None
        if msg and msg.author.id == self.bot.user.id:
            current_content = msg.content or None
        if not status_ping_enabled:
            current_content = None

        if msg:
            try:
                await msg.edit(content=current_content, embed=embed)
                await self.sync_status_pin(channel, msg)
            except Exception:
                print("⚠️ Falha ao editar mensagem existente.")
        else:
            if channel:
                sent = await channel.send(embed=embed)
                self.state["status_message_id"] = sent.id
                await self.save_state()
                await self.sync_status_pin(channel, sent)
                msg = sent
                print("📤 Embed enviado no canal e id salvo.")

        if status_changed and role_id and channel and msg:
            self.pending_status_ping_task = self.bot.loop.create_task(
                self.send_status_ping_notification(
                    channel,
                    msg,
                    role_id,
                    self.state["online"],
                    self.state["last_status_change"]
                )
            )

    # -------------------- Monitor --------------------
    @tasks.loop(seconds=60)
    async def monitor(self):
        url = await get_config(self.db, "kookie_status_url", os.getenv("KOOKIE_STATUS_URL"))
        try:
            st = await get_site_status(url)
        except:
            st = None
        await self.update_state(st)

    @monitor.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()

    # -------------------- Comando /status --------------------
    @app_commands.command(
        name="status",
        description="Mostra o status atual do Kookie"
    )
    async def status_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        chan_id = await get_config(self.db, "status_channel_id", int(os.getenv("STATUS_CHANNEL_ID")))
        msg = await self.get_status_message(chan_id)
        if msg:
            await interaction.followup.send(embed=msg.embeds[0], ephemeral=True)
            return

        self.state["config"] = {"kookie_status_url": await get_config(self.db, "kookie_status_url", os.getenv("KOOKIE_STATUS_URL"))}
        embed = self.build_embed(self.state)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # -------------------- READY --------------------
    @commands.Cog.listener()
    async def on_ready(self):
        if self.monitor_started:
            return

        await self.load_state()

        # Configurações dinâmicas
        chan_id = await get_config(self.db, "status_channel_id", int(os.getenv("STATUS_CHANNEL_ID")))
        url = await get_config(self.db, "kookie_status_url", os.getenv("KOOKIE_STATUS_URL"))
        self.state["config"] = {"kookie_status_url": url}

        # Recupera mensagem existente ou busca manualmente
        msg = await self.get_status_message(chan_id)

        # Reconcilia o tempo que o bot ficou desligado
        now_dt = datetime.now(BR_TZ)
        last_update_ts = self.state.get("last_status_change")
        
        if last_update_ts:
            delta = now_dt.timestamp() - last_update_ts
            if delta > 0:
                if self.state.get("online"):
                    self.state["continuous_online"] += delta
                    print(f"⏳ Bot ficou desligado por {delta:.2f}s. Somado ao tempo contínuo ONLINE.")
                else:
                    self.state["continuous_offline"] += delta
                    print(f"⏳ Bot ficou desligado por {delta:.2f}s. Somado ao tempo contínuo OFFLINE.")
        
        # Atualiza a marca temporal para o presente
        self.state["last_status_change"] = now_dt.timestamp()
        await self.save_state()

        # Atualiza embed
        if msg:
            embed = self.build_embed(self.state)
            try:
                await msg.edit(content=msg.content or None, embed=embed)
                await self.sync_status_pin(self.bot.get_channel(chan_id), msg)
            except Exception as e:
                print("⚠️ Falha ao atualizar mensagem existente:", e)
        else:
            channel = self.bot.get_channel(chan_id)
            if channel:
                embed = self.build_embed(self.state)
                sent = await channel.send(embed=embed)
                self.state["status_message_id"] = sent.id
                await self.save_state()
                await self.sync_status_pin(channel, sent)
                print("📤 Embed enviado no canal e id salvo.")

        # Primeira verificação antes do loop
        try:
            st = await get_site_status(url)
        except:
            st = None
        await self.update_state(st)

        # Inicia monitoramento
        self.monitor.start()
        self.monitor_started = True
        print("🟢 Monitor iniciado e mensagem de status sincronizada com o canal.")


async def setup(bot):
    await bot.add_cog(StatusCog(bot))
