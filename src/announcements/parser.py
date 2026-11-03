"""Busca e interpretação da página de anúncios."""

import logging

import aiohttp
from bs4 import BeautifulSoup

from src.core.http import ensure_public_ip_literal, get_http_session
from src.core.utils import now, parse_brazilian_date
from src.announcements.types import ParsedAnnouncement

logger = logging.getLogger(__name__)


class AnnouncementFetchError(RuntimeError):
    pass


def parse_announcements(html: str, limit: int = 10) -> list[ParsedAnnouncement]:
    # Interpreta o formato configurado; não inventa títulos de registros inválidos.
    if limit <= 0:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".announcement-item")
    if not items:
        logger.warning(
            "Nenhum anúncio encontrado com o seletor .announcement-item; verifique o HTML da página."
        )
    result: list[ParsedAnnouncement] = []
    for item in items:
        title_elem = item.select_one(".announcement-title")
        desc_elem = item.select_one(".announcement-description")
        title = title_elem.get_text(" ", strip=True) if title_elem else ""
        if not title:
            logger.warning("Anúncio ignorado: título ausente ou vazio.")
            continue
        description = desc_elem.get_text(" ", strip=True) if desc_elem else ""
        date_elem = item.select_one(".announcement-date")
        date_text = date_elem.get_text(" ", strip=True) if date_elem else ""
        try:
            date = parse_brazilian_date(date_text) if date_text else now()
        except ValueError:
            date = now()
        result.append(
            {
                "title": title,
                "description": description or "Sem descrição",
                "date": date,
            }
        )
        if len(result) >= limit:
            break
    return result


async def get_kookie_update(
    url: str | None, limit: int = 5, session=None
) -> list[ParsedAnnouncement]:
    if not url:
        raise AnnouncementFetchError("URL de anúncios não configurada.")
    try:
        if session is None:
            ensure_public_ip_literal(url)
            session = get_http_session()
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False
        ) as response:
            if response.status != 200:
                raise AnnouncementFetchError(
                    f"Página de anúncios respondeu HTTP {response.status}."
                )
            return parse_announcements(await response.text(), limit)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise AnnouncementFetchError(
            f"Falha ao consultar página de anúncios ({type(exc).__name__})."
        ) from exc
