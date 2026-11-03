"""Formatos compartilhados de verificações e estado do monitoramento."""

from datetime import datetime
from typing import NotRequired, TypedDict


class StatusCheck(TypedDict):
    online: bool
    http_code: int | None
    response_time: int
    timestamp: datetime
    error: NotRequired[str]


class PersistedStatusCheck(TypedDict):
    online: bool
    http_code: int | None
    response_time: int
    timestamp: str
    error: NotRequired[str]


class StatusConfig(TypedDict):
    kookie_status_url: str | None
    status_old_messages_cleanup_enabled: bool


class StatusState(TypedDict):
    online: bool | None
    last_status_change: float | None
    last_check_ts: float | None
    continuous_online: float
    continuous_offline: float
    total_online: float
    total_offline: float
    downtimes_count: int
    last_http_code: int | None
    last_response_time: int
    last_check: datetime | None
    status_message_id: int | None
    manual_status_start: bool
    config: NotRequired[StatusConfig]


class StatusLogRecord(TypedDict):
    checked_at: str
    online: bool
    http_code: int | None
    response_time: int
