"""Presença rotativa do bot no Discord."""

import logging
from builtins import divmod, float, getattr, int, isinstance, len, max, type
from datetime import datetime, timezone
from typing import Any, cast

import discord
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

PRESENCE_ROTATION = (
    (discord.ActivityType.custom, "👻 Aguardando a volta do Kookie"),
    (discord.ActivityType.custom, "👻🍪 Distribuindo cookies pela comunidade Kookie"),
    (discord.ActivityType.custom, "👻 Monitorando o status do Kookie"),
    (discord.ActivityType.custom, "👻🍪 Passeando pela comunidade Kookie"),
)


class PresenceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activity_index = 0

    def downtime_status(self, *, now=None):
        # Retorna o tempo da queda confirmada, sem contar falhas pendentes.
        get_cog = getattr(self.bot, "get_cog", None)
        status_cog = get_cog("StatusCog") if get_cog else None
        state = getattr(status_cog, "state", {}) if status_cog else {}
        started_at = state.get("last_status_change")
        if state.get("online") is not False or not isinstance(started_at, (int, float)):
            return None

        now_ts = (now or datetime.now(timezone.utc)).timestamp()
        elapsed = max(0, int(now_ts - started_at))
        days, remainder = divmod(elapsed, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        if days:
            duration = f"{days}d"
        elif hours:
            duration = f"{hours}h"
        else:
            duration = f"{minutes}m"
        return f"👻 Já faz {duration} que o Kookie está fora do ar"

    @tasks.loop(seconds=60)
    async def rotate_presence(self):
        downtime_status = self.downtime_status()
        try:
            if downtime_status:
                activity = discord.CustomActivity(name=downtime_status)
            else:
                activity_type, name = PRESENCE_ROTATION[self.activity_index]
                if activity_type is discord.ActivityType.custom:
                    activity = discord.CustomActivity(name=name, emoji="👻")
                else:
                    activity = discord.Activity(type=activity_type, name=name)
            await self.bot.change_presence(activity=activity)
        except discord.HTTPException as exc:
            logger.warning(
                "Falha ao atualizar a presença do bot (%s).", type(exc).__name__
            )
            return
        if not downtime_status:
            self.activity_index = (self.activity_index + 1) % len(PRESENCE_ROTATION)

    @rotate_presence.before_loop
    async def before_rotate_presence(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rotate_presence.is_running():
            self.rotate_presence.start()

    def cog_unload(self):
        cast(Any, self.rotate_presence).cancel()


async def setup(bot):
    await bot.add_cog(PresenceCog(bot))
