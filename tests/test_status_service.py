"""Testes do serviço de estado e persistência do monitoramento."""

import asyncio
import copy
import unittest
from datetime import datetime, timezone

from src.monitoring.service import StatusService
from src.monitoring.types import StatusCheck


def at(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc)


def check(seconds: int, online: bool) -> StatusCheck:
    return {
        "timestamp": at(seconds),
        "online": online,
        "http_code": 200 if online else 503,
        "response_time": 10,
    }


class FakeDatabase:
    def __init__(self):
        self.row = None
        self.logs = []
        self.fail = False

    async def get_state(self):
        return copy.deepcopy(self.row)

    async def save_state(self, state):
        if self.fail:
            raise RuntimeError("Falha de banco")
        self.row = copy.deepcopy(state)

    async def record_check(self, state, data):
        if self.fail:
            raise RuntimeError("Falha de banco")
        self.row = copy.deepcopy(state)
        self.logs.append(copy.deepcopy(data))


class StatusServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_failure_requires_two_consecutive_checks_and_logs_both(self):
        db = FakeDatabase()
        service = StatusService(db)
        await service.record_check(check(100, True))
        self.assertFalse(await service.record_check(check(160, False)))
        self.assertTrue(service.state["online"])
        self.assertEqual(service.pending_failures, 1)
        self.assertFalse(db.logs[-1]["online"])
        self.assertTrue(await service.record_check(check(220, False)))
        self.assertFalse(service.state["online"])
        self.assertEqual(service.pending_failures, 0)
        self.assertEqual(service.state["downtimes_count"], 1)
        self.assertEqual(service.state["total_online"], 120)

    async def test_success_resets_pending_failures_and_recovery_is_immediate(self):
        db = FakeDatabase()
        service = StatusService(db)
        await service.record_check(check(100, True))
        await service.record_check(check(160, False))
        await service.record_check(check(220, True))
        self.assertEqual(service.pending_failures, 0)
        await service.record_check(check(280, False))
        self.assertTrue(service.state["online"])
        await service.record_check(check(340, False))
        self.assertFalse(service.state["online"])
        self.assertTrue(await service.record_check(check(400, True)))
        self.assertTrue(service.state["online"])

    async def test_initial_offline_needs_confirmation(self):
        db = FakeDatabase()
        service = StatusService(db)
        await service.record_check(check(100, False))
        self.assertIsNone(service.state["online"])
        self.assertEqual(service.pending_failures, 1)
        self.assertFalse(await service.record_check(check(160, False)))
        self.assertFalse(service.state["online"])
        self.assertEqual(service.state["downtimes_count"], 0)

    async def test_gap_and_restart_reset_failure_streak(self):
        db = FakeDatabase()
        service = StatusService(db)
        await service.record_check(check(100, True))
        await service.record_check(check(160, False))
        await service.record_check(check(300, False))
        self.assertTrue(service.state["online"])
        self.assertEqual(service.pending_failures, 1)
        restored = StatusService(db)
        await restored.load()
        await restored.record_check(check(360, False))
        self.assertTrue(restored.state["online"])
        self.assertEqual(restored.pending_failures, 1)

    async def test_failed_persistence_does_not_advance_confirmation(self):
        db = FakeDatabase()
        service = StatusService(db)
        await service.record_check(check(100, True))
        db.fail = True
        with self.assertRaises(RuntimeError):
            await service.record_check(check(160, False))
        self.assertEqual(service.pending_failures, 0)
        self.assertTrue(service.state["online"])

    async def test_configured_interval_controls_gap_detection(self):
        db = FakeDatabase()
        service = StatusService(db, failure_confirmations=1, max_gap_seconds=180)
        await service.record_check(check(100, False))
        await service.record_check(check(220, False))
        self.assertEqual(service.state["continuous_offline"], 120)
        await service.record_check(check(340, True))
        self.assertEqual(service.state["total_offline"], 240)

    async def test_manual_offline_survives_checks_restart_and_recovery(self):
        db = FakeDatabase()
        service = StatusService(db, failure_confirmations=1)
        await service.record_check(check(1000, False))
        await service.synchronize_start(at(100), at(1010))
        self.assertEqual(service.state["continuous_offline"], 910)
        self.assertEqual(service.state["total_offline"], 0)
        await service.record_check(check(1060, False))
        self.assertEqual(service.state["continuous_offline"], 960)
        self.assertEqual(service.state["total_offline"], 0)
        restored = StatusService(db, failure_confirmations=1)
        await restored.load()
        await restored.record_check(check(1120, True))
        self.assertEqual(restored.state["continuous_online"], 0)
        self.assertEqual(restored.state["total_offline"], 1020)
        self.assertIsNotNone(db.row)
        assert db.row is not None
        self.assertEqual(db.row["total_offline"], 1020)

    async def test_manual_start_survives_restart_and_long_gap(self):
        db = FakeDatabase()
        service = StatusService(db, failure_confirmations=1)
        await service.record_check(check(1000, False))
        await service.synchronize_start(at(100), at(1010))
        restored = StatusService(db, failure_confirmations=1)
        await restored.load()
        self.assertTrue(restored.state["manual_status_start"])
        await restored.record_check(check(5000, False))
        self.assertEqual(restored.state["last_status_change"], 100)
        self.assertEqual(restored.state["continuous_offline"], 4900)

    async def test_adjustment_preserves_last_completed_period(self):
        db = FakeDatabase()
        service = StatusService(db, failure_confirmations=1)
        await service.record_check(check(100, False))
        service.state["total_offline"] = 500
        await service.record_check(check(160, False))
        await service.synchronize_start(at(130), at(160))
        self.assertEqual(service.state["continuous_offline"], 30)
        self.assertEqual(service.state["total_offline"], 500)
        await service.synchronize_start(at(130), at(160))
        self.assertEqual(service.state["total_offline"], 500)

    async def test_existing_larger_total_is_preserved(self):
        db = FakeDatabase()
        db.row = {"online": True, "continuous_online": 100, "total_online": 500}
        service = StatusService(db, failure_confirmations=1)
        await service.load()
        self.assertEqual(service.state["total_online"], 500)

    async def test_manual_start_survives_gap_and_keeps_last_completed_period(self):
        db = FakeDatabase()
        service = StatusService(db, failure_confirmations=1)
        await service.record_check(check(1000, False))
        service.state["total_offline"] = 90
        await service.synchronize_start(at(100), at(1010))
        await service.record_check(check(2000, False))
        self.assertEqual(service.state["continuous_offline"], 1900)
        self.assertEqual(service.state["total_offline"], 90)

    async def test_persist_failure_does_not_change_memory(self):
        db = FakeDatabase()
        service = StatusService(db, failure_confirmations=1)
        await service.record_check(check(100, False))
        before = copy.deepcopy(service.state)
        db.fail = True
        with self.assertRaises(RuntimeError):
            await service.synchronize_start(at(0), at(110))
        self.assertEqual(service.state, before)

    async def test_stale_check_does_not_overwrite_manual_adjustment(self):
        db = FakeDatabase()
        service = StatusService(db, failure_confirmations=1)
        await service.record_check(check(100, False))
        await service.synchronize_start(at(0), at(120))
        self.assertIsNone(await service.record_check(check(115, True)))
        self.assertFalse(service.state["online"])
        self.assertEqual(service.state["continuous_offline"], 120)
        self.assertEqual(len(db.logs), 1)

    async def test_concurrent_check_and_manual_update_are_serialized(self):
        db = FakeDatabase()
        service = StatusService(db, failure_confirmations=1)
        await service.record_check(check(100, False))
        started, release = asyncio.Event(), asyncio.Event()
        original = db.record_check

        async def slow_save(state, data):
            started.set()
            await release.wait()
            await original(state, data)

        db.record_check = slow_save
        task = asyncio.create_task(service.record_check(check(160, False)))
        await started.wait()
        adjustment = asyncio.create_task(service.synchronize_start(at(0), at(170)))
        release.set()
        await asyncio.gather(task, adjustment)
        self.assertEqual(service.state["total_offline"], 0)
        self.assertIsNotNone(db.row)
        assert db.row is not None
        self.assertEqual(db.row["continuous_offline"], 170)
