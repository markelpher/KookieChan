"""Testes do comando de atualização de anúncios."""

import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from src.cogs.update import UpdateCog
from src.ui.components import PanelContent


class UpdateCommandTest(unittest.IsolatedAsyncioTestCase):
    def make_cog(self, updates):
        cog = cast(Any, object.__new__(UpdateCog))
        cog.repository = SimpleNamespace(list_updates=AsyncMock(return_value=updates))
        cog.publisher = SimpleNamespace(
            build_update_content=lambda items: PanelContent(title=items[0]["title"]),
        )
        return cog

    async def test_prefix_command_reports_when_no_updates_exist(self):
        cog = self.make_cog([])
        ctx = SimpleNamespace(interaction=None, send=AsyncMock())

        await cast(Any, UpdateCog.update_cmd.callback)(cog, ctx)

        ctx.send.assert_awaited_once_with("Nenhuma atualização encontrada.")

    async def test_interaction_command_defers_and_shows_latest_update(self):
        cog = self.make_cog([{"title": "Update"}])
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        ctx = SimpleNamespace(interaction=interaction, send=AsyncMock())

        await cast(Any, UpdateCog.update_cmd.callback)(cog, ctx)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.followup.send.assert_awaited_once()
        self.assertEqual(
            interaction.followup.send.await_args.kwargs["view"].to_components()[0][
                "type"
            ],
            17,
        )

    async def test_repository_failure_returns_safe_message(self):
        cog = self.make_cog([])
        cog.repository.list_updates.side_effect = RuntimeError("sensitive")
        ctx = SimpleNamespace(interaction=None, send=AsyncMock())

        with self.assertLogs("src.cogs.update", level="ERROR") as logs:
            await cast(Any, UpdateCog.update_cmd.callback)(cog, ctx)

        ctx.send.assert_awaited_once_with("❌ Falha ao buscar atualizações.")
        self.assertNotIn("sensitive", logs.output[0])
