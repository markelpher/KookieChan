"""Testes das interfaces de ajuda e histórico."""

import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from discord import app_commands

from src.cogs.help import HelpSelect, HelpView
from src.cogs.history import HISTORY_ITEMS_LIMIT, HistoryCog, HistoryView
from src.ui.components import PanelContent


class HelpTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = SimpleNamespace(
            user=SimpleNamespace(
                display_avatar=SimpleNamespace(url="https://avatar.example/image.png"),
            )
        )
        self.select = HelpSelect(self.bot, "https://news.example")

    def test_all_help_categories_have_expected_content(self):
        for category in ("home", "monitor", "content", "links"):
            with self.subTest(category=category):
                content = self.select.get_content(category)
                self.assertIsNotNone(content)
                assert content is not None
                self.assertTrue(content.title)
        home = self.select.get_content("home")
        links = self.select.get_content("links")
        self.assertIsNotNone(home)
        self.assertIsNotNone(links)
        assert home is not None and links is not None
        self.assertIn("avatar.example", home.thumbnail or "")
        self.assertIn("news.example", links.description)

    async def test_selection_updates_view(self):
        view = HelpView(self.bot, "https://news.example")
        interaction = SimpleNamespace(
            response=SimpleNamespace(edit_message=AsyncMock())
        )
        view.menu._values = ["monitor"]

        await cast(Any, view.menu.callback)(interaction)

        interaction.response.edit_message.assert_awaited_once()

    async def test_timeout_disables_menu_and_edits_message(self):
        view = HelpView(self.bot, "https://news.example")
        cast(Any, view).message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        self.assertTrue(view.menu.disabled)
        cast(Any, view).message.edit.assert_awaited_once_with(view=view)

    async def test_timeout_ignores_discord_edit_failure(self):
        view = HelpView(self.bot, "https://news.example")
        cast(Any, view).message = SimpleNamespace(
            edit=AsyncMock(side_effect=Exception("offline"))
        )
        # O callback captura somente HTTPException; outra exceção deve propagar.
        from discord import HTTPException

        response = SimpleNamespace(status=500, reason="error")
        cast(Any, view).message.edit.side_effect = HTTPException(
            cast(Any, response), "failure"
        )
        await view.on_timeout()


class HistoryTest(unittest.IsolatedAsyncioTestCase):
    def make_cog(self):
        cog = cast(Any, object.__new__(HistoryCog))
        cog.db = SimpleNamespace(list_status=AsyncMock())
        cog.announcements = SimpleNamespace(list_updates=AsyncMock())
        return cog

    async def test_previous_and_next_page_reject_other_users(self):
        owner = object()
        content = PanelContent(title="Page")
        view = HistoryView(SimpleNamespace(user=owner), [content, content])
        unauthorized = SimpleNamespace(
            user=object(),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        await cast(Any, view.next_page)(unauthorized)
        await cast(Any, view.prev_page)(unauthorized)
        self.assertEqual(unauthorized.response.send_message.await_count, 2)
        self.assertEqual(view.index, 0)

    async def test_previous_and_next_page_update_for_owner(self):
        owner = object()
        pages = [PanelContent(title="One"), PanelContent(title="Two")]
        view = HistoryView(SimpleNamespace(user=owner), pages)
        interaction = SimpleNamespace(
            user=owner,
            response=SimpleNamespace(edit_message=AsyncMock()),
        )

        await cast(Any, view.next_page)(interaction)
        self.assertEqual(view.index, 1)
        await cast(Any, view.prev_page)(interaction)
        self.assertEqual(view.index, 0)
        self.assertEqual(interaction.response.edit_message.await_count, 2)

    async def test_status_command_sends_empty_message_and_defers_interaction(self):
        cog = self.make_cog()
        cog.db.list_status.return_value = []
        followup = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock()), followup=followup
        )
        ctx = SimpleNamespace(interaction=interaction, user=object(), send=AsyncMock())

        await cast(Any, HistoryCog.historico.callback)(
            cog, ctx, app_commands.Choice(name="status", value="status")
        )

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        followup.send.assert_awaited_once_with(
            "Nenhum histórico de status encontrado.", ephemeral=True
        )

    async def test_status_history_pages_are_loaded_from_persistent_logs(self):
        cog = self.make_cog()
        cog.db.list_status.return_value = [
            {
                "checked_at": "2026-05-01T12:00:00Z",
                "online": True,
                "http_code": 200,
                "response_time": 42,
            }
        ]

        pages, empty_message = await cog.load_history_pages("status")

        cog.db.list_status.assert_awaited_once_with(HISTORY_ITEMS_LIMIT)
        self.assertEqual(empty_message, "Nenhum histórico de status encontrado.")
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].title, "📊 Histórico de Status do Kookie")

    async def test_update_command_sends_pages_for_prefix_context(self):
        cog = self.make_cog()
        cog.announcements.list_updates.return_value = [
            {
                "date": "2026-05-01T00:00:00Z",
                "title": "News",
                "description": "Text",
            }
        ]
        ctx = SimpleNamespace(interaction=None, user=object(), send=AsyncMock())

        await cast(Any, HistoryCog.historico.callback)(
            cog, ctx, app_commands.Choice(name="update", value="update")
        )

        ctx.send.assert_awaited_once()
        self.assertEqual(
            cog.announcements.list_updates.await_args.args, (HISTORY_ITEMS_LIMIT,)
        )

    async def test_announcement_history_pages_use_database_records(self):
        cog = self.make_cog()
        cog.announcements.list_updates.return_value = [
            {
                "date": "2026-05-01T00:00:00Z",
                "title": "Persisted announcement",
                "description": "Still available after Discord deletion",
                "delivery_status": "sent",
                "delivery_message_id": 123,
            }
        ]

        pages, empty_message = await cog.load_history_pages("update")

        cog.announcements.list_updates.assert_awaited_once_with(HISTORY_ITEMS_LIMIT)
        self.assertEqual(empty_message, "Nenhum histórico de anúncios encontrado.")
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].title, "📢 Persisted announcement")
        self.assertIn("Still available after Discord deletion", pages[0].description)
