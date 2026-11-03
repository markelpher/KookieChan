"""Cliente assíncrono da API REST do Supabase, exclusivo para uso no servidor."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Mapping

import aiohttp

if TYPE_CHECKING:
    from src.monitoring.types import PersistedStatusCheck, StatusState

_db = None


class Database:
    def __init__(self, url, key):
        self.url = url.rstrip("/") + "/rest/v1/"
        self.session = aiohttp.ClientSession(
            headers={
                "apikey": key,
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=20),
        )

    async def request(self, method, path, *, params=None, data=None, prefer=None):
        try:
            return await self._request(
                method, path, params=params, data=data, prefer=prefer
            )
        except aiohttp.ClientError, TimeoutError:
            raise RuntimeError("Falha de conexão com a API do Supabase.") from None

    async def _request(self, method, path, *, params=None, data=None, prefer=None):
        headers = {"Prefer": prefer} if prefer else {}
        async with self.session.request(
            method, self.url + path, params=params, json=data, headers=headers
        ) as response:
            if response.status >= 400:
                code = None
                try:
                    body = await response.json(content_type=None)
                    candidate = body.get("code") if isinstance(body, dict) else None
                    if isinstance(candidate, str) and re.fullmatch(
                        r"(?:[0-9A-Z]{5}|PGRST[0-9]{3})", candidate
                    ):
                        code = candidate
                except ValueError, aiohttp.ContentTypeError:
                    pass
                detail = f" (código {code})" if code else ""
                raise RuntimeError(f"Supabase API HTTP {response.status}{detail}")
            if response.status == 204:
                return None
            text = await response.text()
            if not text:
                return None
            return json.loads(text)

    async def get_config(self, key):
        rows = await self.request(
            "GET", "bot_config", params={"key": f"eq.{key}", "select": "value"}
        )
        return rows[0]["value"] if rows else None

    async def get_configs(self, keys):
        # Busca várias configurações com uma única chamada REST.
        keys = tuple(dict.fromkeys(keys))
        if not keys:
            return {}
        rows = await self.request(
            "GET",
            "bot_config",
            params={
                "key": f"in.({','.join(keys)})",
                "select": "key,value",
            },
        )
        if rows is None:
            return {}
        return {row["key"]: row.get("value") for row in rows}

    async def set_config(self, key, value):
        await self.request(
            "POST",
            "bot_config",
            params={"on_conflict": "key"},
            data={"key": key, "value": value},
            prefer="resolution=merge-duplicates",
        )

    async def set_configs(self, values):
        rows = [{"key": key, "value": value} for key, value in values.items()]
        if rows:
            await self.request(
                "POST",
                "bot_config",
                params={"on_conflict": "key"},
                data=rows,
                prefer="resolution=merge-duplicates",
            )

    async def get_state(self) -> StatusState | None:
        rows = await self.request(
            "GET", "status_state", params={"id": "eq.kookie", "select": "*"}
        )
        if not rows:
            return None
        row = rows[0].copy()
        row.pop("id", None)
        for column, key in (
            ("status_started_at", "last_status_change"),
            ("accounting_at", "last_check_ts"),
        ):
            value = row.pop(column, None)
            row[key] = (
                datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                if value
                else None
            )
        row["manual_status_start"] = row.get("manual_status_start", False)
        value = row.pop("last_check_at", None)
        row["last_check"] = (
            datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
        )
        return row

    @staticmethod
    def state_columns(state: Mapping[str, object]) -> dict[str, object]:
        fields = (
            "online",
            "continuous_online",
            "continuous_offline",
            "total_online",
            "total_offline",
            "downtimes_count",
            "last_http_code",
            "last_response_time",
            "status_message_id",
            "manual_status_start",
        )
        row = {key: state[key] for key in fields if key in state}
        row["manual_status_start"] = state.get("manual_status_start", False)
        for key, column in (
            ("last_status_change", "status_started_at"),
            ("last_check_ts", "accounting_at"),
        ):
            value = state.get(key)
            timestamp = value if isinstance(value, (int, float)) else None
            row[column] = (
                datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
                if timestamp is not None
                else None
            )
        value = state.get("last_check")
        row["last_check_at"] = (
            value.isoformat() if isinstance(value, datetime) else value
        )
        return row

    async def save_state(self, state: Mapping[str, object]) -> None:
        await self.request(
            "POST",
            "status_state",
            params={"on_conflict": "id"},
            data={"id": "kookie", **self.state_columns(state)},
            prefer="resolution=merge-duplicates",
        )

    async def record_check(
        self, state: Mapping[str, object], check: PersistedStatusCheck
    ) -> None:
        await self.request(
            "POST",
            "rpc/record_status_check",
            data={
                "p_state": self.state_columns(state),
                "p_checked_at": check["timestamp"],
                "p_online": check["online"],
                "p_http_code": check["http_code"],
                "p_response_time": check["response_time"],
            },
        )

    async def list_status(self, limit):
        return await self.request(
            "GET",
            "status_logs",
            params={
                "select": "*",
                "order": "checked_at.desc",
                "limit": str(limit),
            },
        )


def get_database():
    if _db is None:
        raise RuntimeError("Banco de dados ainda não inicializado.")
    return _db


async def init_database():
    global _db
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise RuntimeError("Defina SUPABASE_URL e SUPABASE_SECRET_KEY no arquivo .env.")
    _db = Database(url, key)
    try:
        await _db.request("GET", "bot_config", params={"select": "key", "limit": "1"})
    except Exception:
        await _db.session.close()
        _db = None
        raise


async def close_database():
    global _db
    if _db:
        await _db.session.close()
        _db = None
