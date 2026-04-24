import discord
from discord.ext import commands, tasks
from discord import Embed
from datetime import datetime, timedelta
import asyncio
import os
import aiohttp
from bs4 import BeautifulSoup
from database.mongo import get_database
from utils import get_config

# Configurações do MongoDB
COLL_UPDATE = os.getenv("MONGO_UPDATE_COLLECTION", "update")
COLL_ARCHIVE = os.getenv("MONGO_UPDATE_ARCHIVE_COLLECTION", "update_archive")
UPDATE_EMBED_TITLE = "📢 Última atualização do Kookie"

async def get_kookie_update(url, limit=5):
    """
    Busca os últimos anúncios da página de update do Kookie.
    Retorna uma lista de dicionários com 'title', 'description' e 'date'.
    """
    if not url:
        return []
    update_items = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"⚠️ Não foi possível acessar a página de update (HTTP {resp.status})")
                    return update_items

                text = await resp.text()
                soup = BeautifulSoup(text, "html.parser")

                # Ajuste os seletores conforme o HTML real do site
                items = soup.select(".announcement-item")  # cada anúncio
                for item in items[:limit]:
                    title_elem = item.select_one(".announcement-title")
                    desc_elem = item.select_one(".announcement-description")
                    date_elem = item.select_one(".announcement-date")

                    title = title_elem.text.strip() if title_elem else "Sem título"
                    description = desc_elem.text.strip() if desc_elem else "Sem descrição"
                    date_text = date_elem.text.strip() if date_elem else None

                    try:
                        date = datetime.strptime(date_text, "%d/%m/%Y") if date_text else datetime.utcnow()
                    except Exception:
                        date = datetime.utcnow()

                    update_items.append({"title": title, "description": description, "date": date})
    except Exception as e:
        print(f"❌ Erro ao buscar update: {e}")

    return update_items


class UpdateCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()
        self.db_update = self.db[COLL_UPDATE]
        self.db_archive = self.db[COLL_ARCHIVE]
        self.auto_update_started = False
        self.compact_started = False

    async def save_update(self, update):
        exists = await self.db_update.find_one({"title": update["title"]})
        if not exists:
            await self.db_update.insert_one({
                "title": update["title"],
                "description": update["description"],
                "date": update["date"],
                "timestamp": datetime.utcnow()
            })
            return True
        return False

    async def save_update_batch(self, update_items):
        new_update_items = []
        for u in update_items:
            if await self.save_update(u):
                new_update_items.append(u)
        return new_update_items

    def build_update_embed(self, update_items):
        embed = Embed(
            title=UPDATE_EMBED_TITLE,
            color=0xFFD700
        )
        for update in update_items:
            date_str = update["date"].strftime("%d/%m/%Y %H:%M")
            embed.add_field(
                name=f"{update['title']} ({date_str})",
                value=update["description"],
                inline=False
            )
        return embed

    async def fetch_and_save_update(self, limit=5):
        url = await get_config(self.db, "kookie_update_url", os.getenv("KOOKIE_UPDATE_URL"))
        update_items = await get_kookie_update(url, limit)
        new_update_items = await self.save_update_batch(update_items)
        return new_update_items

    async def clear_update_ping(self, message, delay=3):
        if not message:
            return
        try:
            await asyncio.sleep(delay)
            await message.delete()
        except Exception as e:
            print("⚠️ Falha ao limpar ping da mensagem de update:", e)

    async def delete_pin_notification(self, channel):
        try:
            async for msg in channel.history(limit=25):
                if msg.type != discord.MessageType.pins_add:
                    continue
                if msg.author.id != self.bot.user.id:
                    continue
                await msg.delete()
        except Exception as e:
            print("⚠️ Falha ao apagar notificação de mensagem fixada no update:", e)

    async def sync_update_pin(self, channel, message):
        if not channel or not message:
            return

        try:
            pinned_messages = await channel.pins()
        except Exception as e:
            print("⚠️ Falha ao carregar mensagens fixadas de update:", e)
            pinned_messages = []

        already_pinned = False
        for pinned in pinned_messages:
            if pinned.id == message.id:
                already_pinned = True
                continue
            if pinned.author.id != self.bot.user.id:
                continue

            try:
                await pinned.unpin(reason="Substituindo mensagem fixa de update")
            except Exception as e:
                print("⚠️ Falha ao desafixar mensagem antiga de update:", e)

        if already_pinned:
            return

        try:
            await message.pin(reason="Mensagem fixa de update do Kookie")
            await self.delete_pin_notification(channel)
        except discord.HTTPException as e:
            if getattr(e, "code", None) != 30003:
                print("⚠️ Falha ao fixar mensagem de update:", e)
        except Exception as e:
            print("⚠️ Falha ao fixar mensagem de update:", e)

    async def send_update_ping_notification(self, channel, role_id, count):
        if not channel or not role_id:
            return
        suffix = "update novo publicado." if count == 1 else f"{count} update(s) novos publicados."
        content = f"<@&{role_id}> {suffix}"
        try:
            sent = await channel.send(content=content)
            self.bot.loop.create_task(self.clear_update_ping(sent))
            return sent
        except Exception as e:
            print("⚠️ Falha ao enviar notificação de ping de update:", e)
            return None

    async def apply_visual_update_mention(self, channel, message, role_id, delay=3):
        if not channel or not message or not role_id:
            return
        try:
            await asyncio.sleep(delay)
            refreshed_message = message
            try:
                refreshed_message = await channel.fetch_message(message.id)
            except Exception:
                pass

            await refreshed_message.edit(
                content=f"<@&{role_id}>",
                embed=refreshed_message.embeds[0] if refreshed_message.embeds else None
            )
            await self.sync_update_pin(channel, refreshed_message)
        except Exception as e:
            print("⚠️ Falha ao aplicar menção visual na mensagem de update:", e)

    @commands.hybrid_command(name="update", description="Mostra a última atualização ou anúncio do Kookie")
    async def update_cmd(self, ctx):
        display_limit = 1
        if ctx.interaction:
            await ctx.interaction.response.defer(ephemeral=True)
        try:
            await self.fetch_and_save_update(display_limit)
            cursor = self.db_update.find().sort("timestamp", -1).limit(display_limit)
            saved_update_items = await cursor.to_list(length=display_limit)
            if not saved_update_items:
                if ctx.interaction:
                    await ctx.interaction.followup.send("Nenhuma atualização encontrada.", ephemeral=True)
                else:
                    await ctx.send("Nenhuma atualização encontrada.")
                return
            embed = self.build_update_embed(saved_update_items)
            if ctx.interaction:
                await ctx.interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
        except Exception as e:
            if ctx.interaction:
                await ctx.interaction.followup.send(f"❌ Falha ao buscar atualizações: {e}", ephemeral=True)
            else:
                await ctx.send(f"❌ Falha ao buscar atualizações: {e}")

    @tasks.loop(minutes=10)
    async def auto_post_update(self):
        chan_id = await get_config(self.db, "update_channel_id", int(os.getenv("UPDATE_CHANNEL_ID", 0)))
        if chan_id == 0:
            return
        channel = self.bot.get_channel(chan_id)
        if not channel:
            return
        try:
            new_update_items = await self.fetch_and_save_update(limit=10)
            if new_update_items:
                ping_enabled = await get_config(self.db, "update_ping_enabled", False)
                role_id = await get_config(self.db, "update_role_id") if ping_enabled else None
                
                embed = self.build_update_embed(new_update_items)
                main_message = await channel.send(embed=embed)
                await self.sync_update_pin(channel, main_message)
                if role_id:
                    await self.send_update_ping_notification(channel, role_id, len(new_update_items))
                    self.bot.loop.create_task(self.apply_visual_update_mention(channel, main_message, role_id))
                print(f"📢 {len(new_update_items)} novo(s) update enviado(s) no canal.")
        except Exception as e:
            print("❌ Falha ao enviar update automático:", e)

    @tasks.loop(hours=24)
    async def compactar_update_antigo(self):
        cutoff = datetime.utcnow() - timedelta(days=30)
        old_update_cursor = self.db_update.find({"timestamp": {"$lt": cutoff}})
        old_update_items = await old_update_cursor.to_list(length=None)
        if not old_update_items:
            return

        daily_summary = {}
        for update in old_update_items:
            day = update["date"].strftime("%Y-%m-%d")
            if day not in daily_summary:
                daily_summary[day] = {"date": day, "items": []}
            daily_summary[day]["items"].append(update)

        for day_data in daily_summary.values():
            await self.db_archive.update_one({"date": day_data["date"]}, {"$set": day_data}, upsert=True)

        await self.db_update.delete_many({"timestamp": {"$lt": cutoff}})
        print(f"🗂️ Update(s) antigos compactados e deletados ({len(old_update_items)} registros).")

    @compactar_update_antigo.before_loop
    async def before_compactar(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.auto_update_started:
            self.auto_post_update.start()
            self.auto_update_started = True
            print("🟢 Tarefa automática de update iniciada!")
        if not self.compact_started:
            self.compactar_update_antigo.start()
            self.compact_started = True
            print("🟢 Compactação diária de update iniciada!")


async def setup(bot):
    await bot.add_cog(UpdateCog(bot))
