"""Cálculo de tempo observado, independente de Discord e do banco."""

from src.monitoring.types import StatusState

MAX_GAP_SECONDS = 90


def apply_check(
    state: StatusState,
    online: bool,
    checked_at: float,
    max_gap_seconds: float = MAX_GAP_SECONDS,
) -> bool:
    # Só salva o período anterior em transições observadas; lacunas longas são
    # desconhecidas e não devem ser atribuídas a nenhum estado.
    previous = state.get("online")
    last = state.get("last_check_ts")
    if last is not None and checked_at < last:
        raise ValueError("Verificação anterior à última verificação registrada")
    gap = checked_at - last if last is not None else None
    observed = previous is not None and gap is not None and gap <= max_gap_seconds
    changed = previous is not None and previous != online
    if observed and changed:
        assert gap is not None
        if previous:
            state["total_online"] = state.get("continuous_online", 0) + gap
        else:
            state["total_offline"] = state.get("continuous_offline", 0) + gap
    manual_start = state.get("manual_status_start", False)
    if changed:
        state["manual_status_start"] = False
    if (not observed and not (manual_start and not changed)) or changed:
        state["last_status_change"] = checked_at
    if changed and observed and previous:
        state["downtimes_count"] = state.get("downtimes_count", 0) + 1
    state["online"] = online
    state["last_check_ts"] = checked_at
    status_start = state.get("last_status_change")
    duration = max(0, checked_at - status_start) if status_start is not None else 0
    state["continuous_online"] = duration if online else 0
    state["continuous_offline"] = duration if not online else 0
    return changed and observed
