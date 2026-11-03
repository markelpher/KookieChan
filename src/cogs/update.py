"""Comando e agendamento de anúncios no Discord."""

import asyncio
import logging
from typing import Any, cast

from discord.ext import commands, tasks

from src.announcements.delivery import AnnouncementDelivery
from src.announcements.discord import AnnouncementPublisher
from src.announcements.service import AnnouncementService
from src.core.background import cancel_supervised_tasks
from src.core.utils import get_config
from src.database.announcement_repository import AnnouncementRepository
from src.database.database import get_database
from src.ui.components import panel

logger = logging.getLogger(__name__)


async def send_update_response(ctx, *, message=None, view=None):
    response = ctx.interaction.followup if ctx.interaction else ctx
    kwargs = {}
    if view is not None:
        kwargs["view"] = view
    if ctx.interaction:
        kwargs["ephemeral"] = True
    if message is not None:
        await response.send(message, **kwargs)
    else:
        await response.send(**kwargs)


class UpdateCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()
        self.repository = AnnouncementRepository(self.db)
        self.publisher = AnnouncementPublisher(bot, self.db)
        delivery = AnnouncementDelivery(
            self.repository,
            bot.get_channel,
            self.publisher.find_sent_update,
            self.publisher.send_pending_update,
            self.publisher.on_update_delivered,
        )
        self.service = AnnouncementService(self.repository, delivery)
        self.auto_update_started = False

    async def cog_unload(self):
        loop = cast(Any, self.auto_post_update)
        loop.cancel()
        task = loop.get_task()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        await cancel_supervised_tasks(self.bot, owner="announcements")

    async def get_announcement_url(self):
        # Carrega a URL sem impedir o processamento de anúncios pendentes.
        try:
            return await get_config(self.db, "kookie_update_url")
        except Exception as exc:
            logger.warning(
                "Falha ao carregar URL de anúncios (%s).", type(exc).__name__
            )
            return None

    @commands.hybrid_command(
        name="update", description="Mostra a última atualização ou anúncio do Kookie"
    )
    async def update_cmd(self, ctx):
        if ctx.interaction:
            await ctx.interaction.response.defer(ephemeral=True)
        try:
            updates = await self.repository.list_updates(1)
            if not updates:
                await send_update_response(
                    ctx, message="Nenhuma atualização encontrada."
                )
                return
            view = panel(self.publisher.build_update_content(updates))
            await send_update_response(ctx, view=view)
        except Exception as exc:
            logger.error("Falha ao consultar atualizações (%s).", type(exc).__name__)
            await send_update_response(ctx, message="❌ Falha ao buscar atualizações.")

    @tasks.loop(minutes=10)
    async def auto_post_update(self):
        channel_id = None
        try:
            if not await get_config(self.db, "announcements_enabled", True):
                return
            channel_id = await get_config(self.db, "update_channel_id")
            channel = self.bot.get_channel(channel_id) if channel_id else None
            if not channel:
                logger.debug(
                    "Ciclo de anúncios ignorado: canal indisponível (id=%s).",
                    channel_id,
                )
                return
            url = await self.get_announcement_url()
            await self.service.run_cycle(url, channel)
        except Exception as exc:
            logger.error(
                "Falha no ciclo de anúncios do canal id=%s (%s).",
                channel_id,
                type(exc).__name__,
            )

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.auto_update_started:
            self.auto_post_update.start()
            self.auto_update_started = True
            logger.info("Tarefa automática de anúncios iniciada.")


async def setup(bot):
    await bot.add_cog(UpdateCog(bot))
