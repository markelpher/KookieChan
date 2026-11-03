"""Testes das configurações do monitoramento."""

import unittest
from unittest.mock import patch

from src.monitoring.settings import MonitorSettings


class MonitorSettingsTest(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_defaults(self):
        config = MonitorSettings.from_environment()
        self.assertEqual(config.interval_seconds, 60)
        self.assertEqual(config.failure_confirmations, 2)
        self.assertEqual(config.max_gap_seconds, 90)

    @patch.dict(
        "os.environ",
        {"STATUS_CHECK_INTERVAL_SECONDS": "120", "STATUS_FAILURE_CONFIRMATIONS": "3"},
        clear=True,
    )
    def test_custom_values(self):
        config = MonitorSettings.from_environment()
        self.assertEqual(config.max_gap_seconds, 180)
        self.assertEqual(config.failure_confirmations, 3)

    @patch.dict("os.environ", {"STATUS_CHECK_INTERVAL_SECONDS": "0"}, clear=True)
    def test_invalid_interval(self):
        with self.assertRaisesRegex(ValueError, "STATUS_CHECK_INTERVAL_SECONDS"):
            MonitorSettings.from_environment()

    @patch.dict("os.environ", {"STATUS_FAILURE_CONFIRMATIONS": "abc"}, clear=True)
    def test_invalid_confirmation_count(self):
        with self.assertRaisesRegex(ValueError, "STATUS_FAILURE_CONFIRMATIONS"):
            MonitorSettings.from_environment()
