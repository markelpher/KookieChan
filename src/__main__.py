"""Ponto de entrada para executar o bot como módulo."""

import asyncio

from src.main import main

try:
    asyncio.run(main())
except KeyboardInterrupt:
    # main() já registrou a interrupção e fechou as conexões.
    pass
