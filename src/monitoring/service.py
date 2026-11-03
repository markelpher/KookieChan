"""Coordena métricas e persistência, sem depender da interface do Discord."""

import asyncio
from datetime import datetime

from src.monitoring.calculations import apply_check
from src.monitoring.types import PersistedStatusCheck, StatusCheck, StatusState


def initial_state() -> StatusState:
    return {
        "online": None,
        "last_status_change": None,
        "last_check_ts": None,
        "continuous_online": 0.0,
        "continuous_offline": 0.0,
        "total_online": 0.0,
        "total_offline": 0.0,
        "downtimes_count": 0,
        "last_http_code": None,
        "last_response_time": 0,
        "last_check": None,
        "status_message_id": None,
        "manual_status_start": False,
    }


class StatusService:
    # Serializa atualizações no processo e só publica estado após persistir.

    def __init__(
        self, database, *, failure_confirmations: int = 2, max_gap_seconds: float = 90
    ):
        if failure_confirmations < 1 or max_gap_seconds <= 0:
            raise ValueError("Confirmações e intervalo máximo devem ser positivos.")
        self.database = database
        self.state: StatusState = initial_state()
        self._lock = asyncio.Lock()
        self.failure_confirmations = failure_confirmations
        self.max_gap_seconds = max_gap_seconds
        self.pending_failures = 0

    async def load(self):
        async with self._lock:
            raw = await self.database.get_state()
            if raw:
                self.state.update(raw)
            self.pending_failures = 0

    async def record_check(self, check: StatusCheck) -> bool | None:
        checked_at = check["timestamp"]
        async with self._lock:
            # Uma resposta HTTP pode ter sido obtida antes de um ajuste manual.
            last = self.state.get("last_check_ts")
            if last is not None and checked_at.timestamp() < last:
                return None
            next_state = self.state.copy()
            observed_online = check["online"]
            previous = next_state.get("online")
            count = self.pending_failures
            if last is None or checked_at.timestamp() - last > self.max_gap_seconds:
                count = 0
            if not observed_online and previous is not False:
                count += 1
                effective_online = (
                    False if count >= self.failure_confirmations else previous
                )
            else:
                count = 0
                effective_online = observed_online
            if effective_online is None:
                # Ainda não há status confirmado, mas a resposta foi observada.
                next_state["last_check_ts"] = checked_at.timestamp()
                changed = False
            else:
                changed = apply_check(
                    next_state,
                    effective_online,
                    checked_at.timestamp(),
                    self.max_gap_seconds,
                )
                if not effective_online:
                    count = 0
            next_state.update(
                last_http_code=check["http_code"],
                last_response_time=check["response_time"],
                last_check=checked_at,
            )
            persisted_check: PersistedStatusCheck = {
                **check,
                "timestamp": checked_at.isoformat(),
            }
            await self.database.record_check(next_state, persisted_check)
            self.state = next_state
            self.pending_failures = count
            return changed

    async def synchronize_start(self, start: datetime, current: datetime):
        # Corrige o início do período atual sem alterar períodos encerrados.
        start_ts, current_ts = start.timestamp(), current.timestamp()
        if start_ts > current_ts:
            raise ValueError("A data não pode ser no futuro!")
        async with self._lock:
            online = self.state.get("online")
            if online is None:
                raise ValueError("Aguarde a primeira verificação.")
            last = self.state.get("last_check_ts")
            if last is not None and current_ts < last:
                raise ValueError("O estado mudou durante o ajuste. Tente novamente.")
            next_state = self.state.copy()
            duration = current_ts - start_ts
            next_state["continuous_online"] = duration if online else 0.0
            next_state["continuous_offline"] = 0.0 if online else duration
            next_state["last_status_change"] = start_ts
            next_state["manual_status_start"] = True
            next_state["last_check_ts"] = current_ts
            await self.database.save_state(next_state)
            self.state = next_state

    async def reset_metrics(self, current: datetime):
        async with self._lock:
            next_state = self.state.copy()
            next_state.update(
                continuous_online=0.0,
                continuous_offline=0.0,
                total_online=0.0,
                total_offline=0.0,
                downtimes_count=0,
                last_status_change=current.timestamp(),
                last_check_ts=current.timestamp(),
                manual_status_start=False,
            )
            await self.database.save_state(next_state)
            self.state = next_state

    async def set_message_id(self, message_id):
        async with self._lock:
            next_state = self.state.copy()
            next_state["status_message_id"] = message_id
            await self.database.save_state(next_state)
            self.state = next_state
