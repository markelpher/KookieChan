"""Testes das permissões e interações administrativas."""

import os
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import discord

from src.cogs.config import (
    AdminModal,
    AdminPanel,
    ChannelSettingsModal,
    ConfigCog,
    DashboardView,
    NotificationSettingsModal,
    ServiceSettingsModal,
    UrlModal,
    collect_monitor_urls,
    is_authorized_admin,
    open_channel_settings,
    open_notification_settings,
    open_service_settings,
    require_admin,
    select_default_values,
    validate_monitor_url,
    validate_monitor_url_destination,
)
from src.core.utils import get_config


class AdminPermissionsTest(unittest.IsolatedAsyncioTestCase):
    def test_select_defaults_preserve_type_and_allow_empty_value(self):
        role_default = select_default_values("123", discord.SelectDefaultValueType.role)
        channel_default = select_default_values(
            456, discord.SelectDefaultValueType.channel
        )

        self.assertEqual(role_default[0].id, 123)
        self.assertEqual(role_default[0].type, discord.SelectDefaultValueType.role)
        self.assertEqual(channel_default[0].id, 456)
        self.assertEqual(
            channel_default[0].type, discord.SelectDefaultValueType.channel
        )
        self.assertIs(
            select_default_values(None, discord.SelectDefaultValueType.role),
            discord.utils.MISSING,
        )

    def interaction(self, administrator=False, guild=True):
        server = SimpleNamespace(id=1)
        return SimpleNamespace(
            guild=server if guild else None,
            client=SimpleNamespace(guilds=[server]),
            permissions=SimpleNamespace(administrator=administrator),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

    async def test_allows_server_administrator(self):
        interaction = self.interaction(administrator=True)
        self.assertTrue(await require_admin(interaction))
        interaction.response.send_message.assert_not_awaited()

    async def test_denies_non_admin_and_direct_message(self):
        for interaction in (
            self.interaction(),
            self.interaction(administrator=True, guild=False),
        ):
            self.assertFalse(await require_admin(interaction))
            interaction.response.send_message.assert_awaited_once()

    async def test_views_and_modals_revalidate(self):
        for component in (AdminPanel(), AdminModal(title="Teste")):
            interaction = self.interaction()
            self.assertFalse(await component.interaction_check(interaction))

    async def test_command_requires_guild_and_runtime_check(self):
        command = ConfigCog.config_panel
        self.assertTrue(command.guild_only)
        self.assertTrue(command.checks)
        self.assertIn(is_authorized_admin, command.checks)
        self.assertEqual(command.name, "configurações")

    async def test_multi_guild_fails_closed_for_official_single_server_instance(self):
        interaction = self.interaction(administrator=True)
        interaction.client.guilds.append(SimpleNamespace(id=2))
        self.assertFalse(is_authorized_admin(interaction))

    def test_monitor_urls_must_be_absolute_http_urls_without_credentials(self):
        self.assertEqual(
            validate_monitor_url(" https://status.example.com/path "),
            "https://status.example.com/path",
        )
        for url in (
            "",
            "ftp://example.com",
            "https://",
            "https://user:pass@example.com",
            "http://127.0.0.1",
            "http://192.168.1.10",
            "http://localhost",
            "http://printer.local",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_monitor_url(url)

    async def test_monitor_url_dns_resolution_rejects_private_destinations(self):
        with patch("src.configuration.support.asyncio.get_running_loop") as get_loop:
            loop = get_loop.return_value
            loop.getaddrinfo = AsyncMock(
                return_value=[(None, None, None, None, ("10.0.0.4", 0))]
            )
            with self.assertRaisesRegex(ValueError, "privado"):
                await validate_monitor_url_destination("https://status.example")

    def test_monitor_urls_are_optional_and_can_be_saved_independently(self):
        self.assertFalse(UrlModal.status_url.required)
        self.assertFalse(UrlModal.update_url.required)
        self.assertEqual(collect_monitor_urls("", ""), {})
        self.assertEqual(
            collect_monitor_urls("https://status.example", ""),
            {
                "kookie_status_url": "https://status.example",
            },
        )
        self.assertEqual(
            collect_monitor_urls(" ", "https://news.example"),
            {
                "kookie_update_url": "https://news.example",
            },
        )

    async def test_dashboard_notification_selection_opens_modal_directly(self):
        db = SimpleNamespace(get_config=AsyncMock(return_value=None))
        response = SimpleNamespace(send_modal=AsyncMock())
        await open_notification_settings(SimpleNamespace(response=response), db)
        response.send_modal.assert_awaited_once()
        modal = response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, NotificationSettingsModal)
        self.assertEqual(len(modal.children), 4)

    async def test_dashboard_channel_and_service_settings_open_modals(self):
        db = SimpleNamespace(get_config=AsyncMock(return_value=None))
        for opener, expected in (
            (open_channel_settings, ChannelSettingsModal),
            (open_service_settings, ServiceSettingsModal),
        ):
            response = SimpleNamespace(send_modal=AsyncMock())
            await opener(SimpleNamespace(response=response), db)
            modal = response.send_modal.await_args.args[0]
            self.assertIsInstance(modal, expected)
            if isinstance(modal, ServiceSettingsModal):
                self.assertTrue(modal.status_cleanup_select.options[1].default)

    async def test_channel_and_service_modals_persist_all_values(self):
        db = SimpleNamespace(
            get_config=AsyncMock(return_value=None),
            set_configs=AsyncMock(),
        )
        interaction = SimpleNamespace(
            client=SimpleNamespace(),
            response=SimpleNamespace(edit_message=AsyncMock(), is_done=lambda: True),
        )

        channels = ChannelSettingsModal(db)
        cast(Any, channels.status_channel_select)._values = [SimpleNamespace(id=111)]
        cast(Any, channels.update_channel_select)._values = [SimpleNamespace(id=222)]
        await cast(Any, channels.on_submit)(interaction)
        db.set_configs.assert_awaited_with(
            {"status_channel_id": 111, "update_channel_id": 222}
        )

        services = ServiceSettingsModal(db)
        services.status_select._values = ["false"]
        services.announcements_select._values = ["true"]
        services.status_cleanup_select._values = ["true"]
        await cast(Any, services.on_submit)(interaction)
        db.set_configs.assert_awaited_with(
            {
                "status_monitor_enabled": False,
                "announcements_enabled": True,
                "status_old_messages_cleanup_enabled": True,
            }
        )
        self.assertEqual(interaction.response.edit_message.await_count, 2)

    async def test_notification_modal_saves_settings_and_returns_to_dashboard(self):
        db = SimpleNamespace(
            get_config=AsyncMock(return_value=None),
            set_configs=AsyncMock(),
        )
        modal = NotificationSettingsModal(db)
        cast(Any, modal.status_role_select)._values = [SimpleNamespace(id=123)]
        cast(Any, modal.update_role_select)._values = []
        modal.status_ping_select._values = ["true"]
        modal.update_ping_select._values = ["false"]
        interaction = SimpleNamespace(
            client=SimpleNamespace(),
            response=SimpleNamespace(edit_message=AsyncMock(), is_done=lambda: True),
        )

        await cast(Any, modal.on_submit)(interaction)

        db.set_configs.assert_awaited_once_with(
            {
                "status_role_id": 123,
                "update_role_id": "",
                "status_ping_enabled": True,
                "update_ping_enabled": False,
            }
        )
        interaction.response.edit_message.assert_awaited_once()
        self.assertIsInstance(
            interaction.response.edit_message.await_args.kwargs["view"], DashboardView
        )

    async def test_notification_modal_saves_when_everything_is_empty(self):
        db = SimpleNamespace(
            get_config=AsyncMock(return_value=None),
            set_configs=AsyncMock(),
        )
        modal = NotificationSettingsModal(db)
        modal.status_ping_select._values = []
        modal.update_ping_select._values = []
        interaction = SimpleNamespace(
            client=SimpleNamespace(),
            response=SimpleNamespace(edit_message=AsyncMock(), is_done=lambda: True),
        )

        await cast(Any, modal.on_submit)(interaction)

        db.set_configs.assert_awaited_once_with(
            {
                "status_role_id": "",
                "update_role_id": "",
                "status_ping_enabled": False,
                "update_ping_enabled": False,
            }
        )

    async def test_saving_urls_returns_to_the_existing_configuration_menu(self):
        db = SimpleNamespace(
            get_config=AsyncMock(return_value=None),
            set_configs=AsyncMock(),
        )
        source_interaction = SimpleNamespace()
        confirmation = SimpleNamespace(delete=AsyncMock())
        scheduled = []
        modal = UrlModal(source_interaction)
        modal.status_url._value = "https://status.example"
        modal.update_url._value = ""
        bot = SimpleNamespace(
            user=SimpleNamespace(
                display_avatar=SimpleNamespace(url="https://avatar.example")
            )
        )
        interaction = SimpleNamespace(
            client=bot,
            response=SimpleNamespace(edit_message=AsyncMock(), is_done=lambda: True),
            followup=SimpleNamespace(send=AsyncMock(return_value=confirmation)),
            delete_original_response=AsyncMock(),
        )
        with (
            patch("src.configuration.forms.get_database", return_value=db),
            patch(
                "src.configuration.support.validate_monitor_url_destination",
                new=AsyncMock(side_effect=lambda url: url),
            ),
            patch(
                "src.configuration.support.asyncio.create_task",
                side_effect=scheduled.append,
            ),
        ):
            await cast(Any, modal.on_submit)(interaction)
        db.set_configs.assert_awaited_once_with(
            {"kookie_status_url": "https://status.example"}
        )
        interaction.response.edit_message.assert_awaited_once()
        interaction.delete_original_response.assert_not_awaited()
        interaction.followup.send.assert_awaited_once_with(
            "URLs preenchidas salvas.",
            ephemeral=True,
            wait=True,
        )
        self.assertEqual(len(scheduled), 1)
        with patch("src.configuration.support.asyncio.sleep", new=AsyncMock()) as sleep:
            await scheduled[0]
        sleep.assert_awaited_once_with(10)
        confirmation.delete.assert_awaited_once_with()
        interaction.delete_original_response.assert_not_awaited()

    async def test_operational_settings_do_not_fall_back_to_environment(self):
        database = SimpleNamespace(get_config=AsyncMock(return_value=None))
        with patch.dict(
            os.environ,
            {"STATUS_CHANNEL_ID": "123", "KOOKIE_STATUS_URL": "https://old.example"},
        ):
            self.assertIsNone(await get_config(database, "status_channel_id"))
            self.assertEqual(
                await get_config(database, "kookie_status_url", "default"), "default"
            )
