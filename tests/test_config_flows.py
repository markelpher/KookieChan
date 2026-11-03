"""Testes dos fluxos de configuração administrativa."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.cogs.config import (
    DEFAULT_DASHBOARD_SETTINGS,
    apply_data_action,
    build_dashboard_content,
    delete_previous_status_message,
    get_config_values,
    get_dashboard_content,
    restore_status_message,
    save_modal_settings,
    send_temporary_confirmation,
    validate_monitor_url_destination,
    validate_monitor_urls,
)
from src.core.utils import BR_TZ


class ConfigFlowTest(unittest.IsolatedAsyncioTestCase):
    def make_status_recovery(self, *, author_id=55):
        message = SimpleNamespace(
            id=123,
            author=SimpleNamespace(id=author_id),
            jump_url="https://discord.example/messages/123",
        )
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        status_cog = SimpleNamespace(
            db=object(),
            state={"status_message_id": None},
            load_status_config=AsyncMock(),
            cleanup_old_status_messages=AsyncMock(),
            build_status_content=lambda state: "content",
            service=SimpleNamespace(set_message_id=AsyncMock()),
            sync_status_pin=AsyncMock(),
        )
        interaction = SimpleNamespace(
            client=SimpleNamespace(user=SimpleNamespace(id=55)),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        return interaction, status_cog, channel, message

    async def test_data_action_synchronizes_parsed_date_with_brazilian_timestamp(self):
        parsed_date = datetime(2026, 8, 28, tzinfo=timezone.utc)
        service = SimpleNamespace(synchronize_start=AsyncMock())
        status_cog = SimpleNamespace(service=service)

        with patch(
            "src.configuration.support.parse_brazilian_date", return_value=parsed_date
        ) as parse_date:
            await apply_data_action(status_cog, "sync", "28/08/2026")

        parse_date.assert_called_once_with("28/08/2026")
        service.synchronize_start.assert_awaited_once()
        actual_date, started_at = service.synchronize_start.await_args.args
        self.assertEqual(actual_date, parsed_date)
        self.assertEqual(started_at.tzinfo, BR_TZ)

    async def test_data_action_resets_metrics_and_requires_sync_date(self):
        service = SimpleNamespace(
            synchronize_start=AsyncMock(), reset_metrics=AsyncMock()
        )
        status_cog = SimpleNamespace(service=service)

        await apply_data_action(status_cog, "reset", "")

        service.reset_metrics.assert_awaited_once()
        self.assertEqual(service.reset_metrics.await_args.args[0].tzinfo, BR_TZ)
        with self.assertRaisesRegex(ValueError, "Informe uma data"):
            await apply_data_action(status_cog, "sync", "")
        service.synchronize_start.assert_not_awaited()

    async def test_previous_status_cleanup_deletes_only_bot_messages(self):
        bot_user = SimpleNamespace(id=55)
        current_message = SimpleNamespace(id=123)
        old_bot_message = SimpleNamespace(
            id=100, author=SimpleNamespace(id=55), delete=AsyncMock()
        )
        old_user_message = SimpleNamespace(
            id=101, author=SimpleNamespace(id=99), delete=AsyncMock()
        )
        channel = SimpleNamespace(
            fetch_message=AsyncMock(side_effect=[old_bot_message, old_user_message])
        )

        await delete_previous_status_message(channel, 100, current_message, bot_user)
        await delete_previous_status_message(channel, 101, current_message, bot_user)

        old_bot_message.delete.assert_awaited_once_with()
        old_user_message.delete.assert_not_awaited()

    async def test_bulk_config_values_apply_defaults_for_missing_and_null_values(self):
        db = SimpleNamespace(
            get_configs=AsyncMock(
                return_value={
                    "present": 5,
                    "null": None,
                }
            )
        )

        result = await get_config_values(
            db,
            ("present", "null", "missing"),
            {
                "null": "fallback-null",
                "missing": "fallback-missing",
            },
        )

        self.assertEqual(
            result,
            {
                "present": 5,
                "null": "fallback-null",
                "missing": "fallback-missing",
            },
        )
        db.get_configs.assert_awaited_once()

    async def test_legacy_database_fetches_config_values_individually(self):
        db = SimpleNamespace(get_config=AsyncMock(side_effect=[1, None]))

        result = await get_config_values(db, ("one", "two"), {"two": 2})

        self.assertEqual(result, {"one": 1, "two": 2})
        self.assertEqual(db.get_config.await_count, 2)

    async def test_dashboard_formats_channels_urls_services_and_roles(self):
        values = {
            "status_channel_id": 11,
            "update_channel_id": None,
            "kookie_status_url": "https://status.example",
            "kookie_update_url": None,
            "status_monitor_enabled": True,
            "announcements_enabled": False,
            "status_old_messages_cleanup_enabled": False,
            "status_ping_enabled": True,
            "update_ping_enabled": False,
            "status_role_id": 22,
            "update_role_id": None,
        }
        db = SimpleNamespace(get_configs=AsyncMock(return_value=values))

        content = await get_dashboard_content(db)

        sections = dict(content.sections)
        self.assertIn("<#11>", sections["Monitoramento"])
        self.assertIn("https://status.example", sections["URLs monitoradas"])
        self.assertIn("Desativados", sections["Serviços automáticos"])
        self.assertIn("<@&22>", sections["Notificações de status"])

    def test_dashboard_formatting_uses_defaults_without_database_access(self):
        content = build_dashboard_content(DEFAULT_DASHBOARD_SETTINGS)

        sections = dict(content.sections)
        self.assertIn("Não definido", sections["Monitoramento"])
        self.assertIn("Não definida", sections["URLs monitoradas"])
        self.assertIn("Ativado", sections["Serviços automáticos"])
        self.assertIn("Desativado", sections["Notificações de status"])

    async def test_status_message_recovery_updates_and_pins_bot_message(self):
        interaction, status_cog, channel, message = self.make_status_recovery()
        with (
            patch(
                "src.configuration.support.get_config",
                new=AsyncMock(return_value="https://status.example"),
            ),
            patch("src.configuration.forms.message_contains_title", return_value=True),
            patch("src.configuration.forms.panel", return_value="panel"),
            patch("src.configuration.forms.edit_panel", new=AsyncMock()) as edit,
        ):
            await restore_status_message(interaction, status_cog, channel, message.id)

        edit.assert_awaited_once_with(message, "panel")
        status_cog.load_status_config.assert_awaited_once_with()
        status_cog.cleanup_old_status_messages.assert_awaited_once_with(
            channel, message
        )
        status_cog.service.set_message_id.assert_awaited_once_with(message.id)
        status_cog.sync_status_pin.assert_awaited_once_with(channel, message)
        interaction.response.send_message.assert_awaited_once_with(
            "Mensagem de status recuperada com sucesso: "
            "[ir para mensagem](https://discord.example/messages/123)",
            ephemeral=True,
        )

    async def test_status_message_recovery_rejects_message_from_another_author(self):
        interaction, status_cog, channel, message = self.make_status_recovery(
            author_id=99
        )
        with (
            patch(
                "src.configuration.support.get_config", new=AsyncMock(return_value=None)
            ),
            patch("src.configuration.forms.message_contains_title", return_value=True),
            self.assertLogs("src.cogs.config", level="WARNING"),
        ):
            await restore_status_message(interaction, status_cog, channel, message.id)

        status_cog.service.set_message_id.assert_not_awaited()
        status_cog.load_status_config.assert_awaited_once_with()
        status_cog.sync_status_pin.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once_with(
            "Não foi possível recuperar a mensagem de status.", ephemeral=True
        )

    async def test_status_message_recovery_reports_fetch_failure_without_details(self):
        interaction, status_cog, channel, message = self.make_status_recovery()
        channel.fetch_message.side_effect = RuntimeError("private discord details")

        with self.assertLogs("src.cogs.config", level="WARNING") as logs:
            await restore_status_message(interaction, status_cog, channel, message.id)

        self.assertNotIn("private discord details", logs.output[0])
        status_cog.load_status_config.assert_not_awaited()
        status_cog.service.set_message_id.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once_with(
            "Falha ao buscar a mensagem.", ephemeral=True
        )

    async def test_save_settings_reports_database_failure(self):
        db = SimpleNamespace(set_configs=AsyncMock(side_effect=RuntimeError("secret")))
        interaction = SimpleNamespace(
            response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
        )

        with self.assertLogs("src.cogs.config", level="ERROR") as logs:
            result = await save_modal_settings(
                interaction,
                db,
                {"key": "value"},
                failure_message="Não salvou.",
            )

        self.assertFalse(result)
        interaction.response.send_message.assert_awaited_once_with(
            "Não salvou.", ephemeral=True
        )
        self.assertNotIn("secret", logs.output[0])

    async def test_save_settings_reports_dashboard_refresh_failure_after_persisting(
        self,
    ):
        db = SimpleNamespace(set_configs=AsyncMock())
        interaction = SimpleNamespace(
            response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
        )
        with patch(
            "src.configuration.views.show_dashboard",
            new=AsyncMock(side_effect=RuntimeError("offline")),
        ):
            result = await save_modal_settings(
                interaction, db, {"key": "value"}, failure_message="failed"
            )

        self.assertFalse(result)
        db.set_configs.assert_awaited_once_with({"key": "value"})
        self.assertIn(
            "Reabra /configurações.",
            interaction.response.send_message.await_args.args[0],
        )

    async def test_confirmation_without_message_does_not_schedule_task(self):
        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=AsyncMock(return_value=None))
        )
        with patch("src.configuration.support.supervise_task") as supervise:
            await send_temporary_confirmation(interaction, "Saved")
        supervise.assert_not_called()

    async def test_url_validation_resolves_public_host_and_rejects_dns_error(self):
        with patch("src.configuration.support.asyncio.get_running_loop") as get_loop:
            get_loop.return_value.getaddrinfo = AsyncMock(
                return_value=[
                    (None, None, None, None, ("8.8.8.8", 0)),
                ]
            )
            result = await validate_monitor_url_destination("https://example.org")
            self.assertEqual(result, "https://example.org")

            import socket

            get_loop.return_value.getaddrinfo.side_effect = socket.gaierror()
            with self.assertRaisesRegex(ValueError, "resolver"):
                await validate_monitor_url_destination("https://missing.example")

    async def test_monitor_url_flow_validates_each_populated_destination(self):
        with patch(
            "src.configuration.support.validate_monitor_url_destination",
            new=AsyncMock(side_effect=lambda url: url),
        ) as validate_destination:
            urls = await validate_monitor_urls(
                "https://status.example", "https://news.example"
            )

        self.assertEqual(
            urls,
            {
                "kookie_status_url": "https://status.example",
                "kookie_update_url": "https://news.example",
            },
        )
        self.assertEqual(
            validate_destination.await_args_list[0].args,
            ("https://status.example",),
        )
        self.assertEqual(
            validate_destination.await_args_list[1].args,
            ("https://news.example",),
        )
