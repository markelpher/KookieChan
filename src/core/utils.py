"""Funções utilitárias compartilhadas pela aplicação."""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING

import aiohttp
import pytz

from src.core.http import ensure_public_ip_literal, get_http_session

if TYPE_CHECKING:
    from src.monitoring.types import StatusCheck

# GMT-3 fixo, independentemente de regras históricas de horário de verão.
BR_TZ = pytz.FixedOffset(-180)


def parse_brazilian_date(date_str: str) -> datetime:
    # Converte data local em GMT-3 para datetime com fuso.
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y %H:%M")
        return BR_TZ.localize(dt)
    except ValueError:
        try:
            dt = datetime.strptime(date_str, "%d/%m/%Y")
            return BR_TZ.localize(dt.replace(hour=0, minute=0))
        except ValueError:
            raise ValueError("Formato de data inválido. Use DD/MM/AAAA HH:MM")


async def get_config(db, key, default=None):
    # Busca configuração persistida e usa o valor padrão se ainda não foi definida.
    value = await db.get_config(key)
    return value if value is not None else default


async def set_config(db, key, value):
    # Salva uma configuração sem sobrescrever as demais.
    await db.set_config(key, value)


def now() -> datetime:
    # Retorna a hora atual no fuso horário BR_TZ.
    return datetime.now(tz=BR_TZ)


def format_datetime_br(dt: datetime | str) -> str:
    # Formata uma data no fuso GMT-3 (datas sem fuso são consideradas UTC).
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytz.utc).astimezone(BR_TZ)
    else:
        dt = dt.astimezone(BR_TZ)
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def discord_timestamp(dt: datetime) -> str:
    # Instante renderizado pelo Discord no fuso de quem lê.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytz.utc)
    return f"<t:{int(dt.timestamp())}:F>"


def announcement_date(dt: datetime) -> str:
    # Data civil do anúncio, interpretada no fuso da fonte, sem horário.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytz.utc)
    return dt.astimezone(BR_TZ).strftime("%d/%m/%Y")


def ms_to_str(ms: float) -> str:
    # Formata a duração em minutos, horas/minutos ou dias/horas/minutos.
    seconds = int(ms / 1000)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)

    if d > 0:
        return f"{d}d {h}h {m:02d}m"
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


async def get_site_status(url: str, session=None) -> StatusCheck:
    # Faz requisição HTTP ao site e retorna status, código, tempo e timestamp.
    start_time = time.monotonic()
    try:
        if session is None:
            ensure_public_ip_literal(url)
            session = get_http_session()
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False
        ) as response:
            response_time = int((time.monotonic() - start_time) * 1000)
            code = response.status
            online = 200 <= code < 300
            return {
                "online": online,
                "http_code": code,
                "response_time": response_time,
                "timestamp": now(),
            }
    except Exception as e:
        return {
            "online": False,
            "http_code": None,
            "response_time": 0,
            "timestamp": now(),
            "error": type(e).__name__,
        }
