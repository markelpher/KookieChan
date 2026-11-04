"""Testes dos componentes e painéis interativos do Discord."""

import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from src.cogs.config import (
    ChannelSettingsModal,
    DashboardView,
    DataModal,
    NotificationSettingsModal,
    ServiceSettingsModal,
)
from src.cogs.help import HelpView
from src.cogs.history import HistoryView
from src.ui.components import PanelContent, edit_panel, message_contains_title, panel


class ComponentsTest(unittest.IsolatedAsyncioTestCase):
    async def test_views_have_v2_content_and_wrapped_controls(self):
        content = PanelContent(
            title="Teste", description="Conteúdo", sections=(("Detalhe", "Valor"),)
        )
        views = [
            DashboardView(None, None),
            HelpView(None, "https://kookie.app/announcements"),
            HistoryView(None, [content]),
        ]
        for view in views:
            with self.subTest(view=type(view).__name__):
                components = view.set_content(content).to_components()
                self.assertEqual(components[0]["type"], 17)
                self.assertTrue(all(item["type"] == 1 for item in components[1:]))
                self.assertTrue(any(item["components"] for item in components[1:]))

    async def test_v2_message_edit(self):
        view = panel(PanelContent(title="Status do Kookie"))
        message = SimpleNamespace(edit=AsyncMock())
        await edit_panel(message, view)
        self.assertNotIn("embeds", message.edit.call_args.kwargs)
        self.assertNotIn("content", message.edit.call_args.kwargs)

    async def test_notification_settings_use_modal_with_role_and_toggle_selectors(self):
        modal = NotificationSettingsModal(
            None,
            status_role_id=123,
            update_role_id=456,
            status_ping_enabled=True,
            update_ping_enabled=False,
        )
        components = modal.to_components()
        self.assertEqual(len(components), 4)
        self.assertTrue(all(component["type"] == 18 for component in components))
        self.assertEqual(
            [component["component"]["type"] for component in components], [6, 6, 3, 3]
        )
        self.assertEqual(components[0]["component"]["default_values"][0]["id"], 123)
        self.assertTrue(components[2]["component"]["options"][0]["default"])
        self.assertTrue(components[3]["component"]["options"][1]["default"])
        self.assertFalse(modal.status_ping_select.required)
        self.assertFalse(modal.update_ping_select.required)
        self.assertEqual(modal.status_ping_select.min_values, 0)

    async def test_other_settings_use_compact_modals(self):
        channels = ChannelSettingsModal(
            None, status_channel_id=100, update_channel_id=200
        )
        self.assertEqual(
            [item["component"]["type"] for item in channels.to_components()], [8, 8]
        )
        self.assertEqual(
            channels.to_components()[0]["component"]["default_values"][0]["id"], 100
        )

        services = ServiceSettingsModal(
            None, status_enabled=False, announcements_enabled=True
        )
        service_components = services.to_components()
        self.assertEqual(
            [item["component"]["type"] for item in service_components], [3, 3, 3]
        )
        self.assertTrue(service_components[0]["component"]["options"][1]["default"])
        self.assertTrue(service_components[1]["component"]["options"][0]["default"])
        self.assertTrue(service_components[2]["component"]["options"][1]["default"])

        data = DataModal(None)
        self.assertEqual([item["type"] for item in data.to_components()], [18, 18])
        self.assertFalse(data.data_input.required)
        self.assertEqual(
            {option.value for option in data.action_select.options},
            {"sync", "reset"},
        )

    async def test_dashboard_routes_each_category_to_its_modal(self):
        db = SimpleNamespace(get_config=AsyncMock(return_value=None))
        view = DashboardView(None, db)
        selector = cast(Any, view.children[0]).children[0]
        categories = (
            "canais",
            "urls",
            "servicos",
            "tempo",
            "pings",
            "mensagem_fixa",
        )

        for category in categories:
            with self.subTest(category=category):
                selector._values = [category]
                interaction = SimpleNamespace(
                    response=SimpleNamespace(send_modal=AsyncMock())
                )
                await cast(Any, selector.callback)(interaction)
                interaction.response.send_modal.assert_awaited_once()

    async def test_recognizes_status_components(self):
        v2 = SimpleNamespace(
            components=[
                SimpleNamespace(
                    children=[SimpleNamespace(content="# Status do Kookie")]
                )
            ]
        )
        self.assertTrue(message_contains_title(v2, "Status do Kookie"))
