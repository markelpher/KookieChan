"""Configurações validadas do monitor de disponibilidade."""

import os
from dataclasses import dataclass


def _integer_setting(name, default, minimum, maximum):
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{name} deve ser um inteiro entre {minimum} e {maximum}."
        ) from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} deve ser um inteiro entre {minimum} e {maximum}.")
    return value


@dataclass(frozen=True)
class MonitorSettings:
    interval_seconds: int = 60
    failure_confirmations: int = 2

    @property
    def max_gap_seconds(self) -> float:
        return self.interval_seconds * 1.5

    @classmethod
    def from_environment(cls):
        return cls(
            interval_seconds=_integer_setting(
                "STATUS_CHECK_INTERVAL_SECONDS", 60, 15, 3600
            ),
            failure_confirmations=_integer_setting(
                "STATUS_FAILURE_CONFIRMATIONS", 2, 1, 10
            ),
        )
