"""Testes das validações de segurança das requisições HTTP."""

import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from src.core.http import PublicResolver, ensure_public_ip_literal


class HttpSecurityTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolver_rejects_private_address_for_public_hostname(self):
        resolver = PublicResolver()
        cast(Any, resolver)._resolver = SimpleNamespace(
            resolve=AsyncMock(return_value=[{"host": "10.1.2.3"}])
        )
        with self.assertRaisesRegex(OSError, "privado"):
            await resolver.resolve("public-looking.example", 443)

    async def test_resolver_accepts_global_addresses(self):
        record = {"host": "8.8.8.8"}
        resolver = PublicResolver()
        cast(Any, resolver)._resolver = SimpleNamespace(
            resolve=AsyncMock(return_value=[record])
        )
        self.assertEqual(await resolver.resolve("dns.example", 443), [record])

    def test_ip_literal_filter_blocks_non_public_destinations(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "[::1]"):
            with (
                self.subTest(address=address),
                self.assertRaisesRegex(ValueError, "privado"),
            ):
                ensure_public_ip_literal(f"http://{address}/")

    def test_ip_literal_filter_allows_global_destination(self):
        ensure_public_ip_literal("https://8.8.8.8/dns-query")
