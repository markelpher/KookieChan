"""Testes das regras de cálculo do monitoramento de status."""

import unittest
from typing import cast

from src.monitoring.calculations import apply_check
from src.monitoring.types import StatusState


class MonitoringTest(unittest.TestCase):
    def make_state(self, **values):
        return cast(StatusState, values)

    def test_intervals_and_transition(self):
        s = cast(StatusState, {})
        self.assertFalse(apply_check(s, True, 100))
        self.assertFalse(apply_check(s, True, 160))
        self.assertEqual(s["continuous_online"], 60)
        self.assertTrue(apply_check(s, False, 220))
        self.assertEqual(s["total_online"], 120)
        self.assertEqual(s["continuous_offline"], 0)
        self.assertEqual(s["downtimes_count"], 1)
        apply_check(s, False, 280)
        self.assertEqual(s.get("total_offline", 0), 0)
        apply_check(s, True, 340)
        self.assertEqual(s["total_offline"], 120)
        apply_check(s, False, 400)
        self.assertEqual(s["total_online"], 60)

    def test_gap_is_not_counted_or_inferred_as_outage(self):
        s = cast(StatusState, {})
        apply_check(s, True, 100)
        self.assertFalse(apply_check(s, False, 1000))
        self.assertEqual(s.get("total_online", 0), 0)
        self.assertEqual(s.get("downtimes_count", 0), 0)
        self.assertEqual(s["continuous_offline"], 0)

    def test_same_status_after_gap_restarts_continuity(self):
        s = cast(StatusState, {})
        apply_check(s, True, 0)
        apply_check(s, True, 60)
        apply_check(s, True, 1000)
        self.assertEqual(s["continuous_online"], 0)
        self.assertEqual(s.get("total_online", 0), 0)

    def test_manual_start_survives_gap_while_same_status_continues(self):
        s = cast(StatusState, {
            "online": False,
            "last_check_ts": 100,
            "last_status_change": 0,
            "manual_status_start": True,
        })
        apply_check(s, False, 1000)
        self.assertEqual(s["last_status_change"], 0)
        self.assertEqual(s["continuous_offline"], 1000)
        self.assertTrue(s["manual_status_start"])

    def test_manual_start_is_cleared_on_status_transition(self):
        s = cast(StatusState, {
            "online": False,
            "last_check_ts": 100,
            "last_status_change": 0,
            "manual_status_start": True,
        })
        apply_check(s, True, 1000)
        self.assertFalse(s["manual_status_start"])
        self.assertEqual(s["last_status_change"], 1000)

    def test_out_of_order_rejected(self):
        s = cast(StatusState, {})
        apply_check(s, True, 100)
        with self.assertRaises(ValueError):
            apply_check(s, False, 99)

    def test_transition_after_gap_does_not_replace_last_period(self):
        s = cast(StatusState, {"total_offline": 300})
        apply_check(s, False, 100)
        self.assertFalse(apply_check(s, True, 1000))
        self.assertEqual(s["total_offline"], 300)

    def test_later_period_replaces_previous_instead_of_accumulating(self):
        s = cast(StatusState, {"total_offline": 300})
        apply_check(s, False, 100)
        apply_check(s, True, 160)
        self.assertEqual(s["total_offline"], 60)


if __name__ == "__main__":
    unittest.main()
