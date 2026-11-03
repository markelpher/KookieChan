"""Sessão HTTP reutilizada pelos serviços externos do bot."""

import ipaddress
import socket
from urllib.parse import urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult


class PublicResolver(AbstractResolver):
    # Bloqueia DNS rebinding para redes privadas na conexão efetiva.

    def __init__(self):
        self._resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_UNSPEC,
    ) -> list[ResolveResult]:
        records = await self._resolver.resolve(host, port, family)
        if not records or any(
            not ipaddress.ip_address(record["host"]).is_global for record in records
        ):
            raise OSError("Hostname resolve para endereço privado ou reservado.")
        return records

    async def close(self):
        await self._resolver.close()


_session = None


def get_http_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "KookieChan/1.0"},
            connector=aiohttp.TCPConnector(resolver=PublicResolver()),
        )
    return _session


def ensure_public_ip_literal(url):
    # Aiohttp não usa o resolver configurado para literais IP.
    host = urlsplit(url).hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError, TypeError:
        return
    if not address.is_global:
        raise ValueError("Destino IP privado ou reservado bloqueado.")


async def close_http_session():
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None
