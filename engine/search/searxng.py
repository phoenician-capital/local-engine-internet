"""Optional self-hosted SearXNG provider."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings
from .base import Hit

logger = logging.getLogger("engine.search.searxng")

NAME = "searxng"


def enabled() -> bool:
    return bool(settings.searxng_url)


def parse_searxng_payload(payload: dict[str, Any], query: str = "") -> list[Hit]:
    hits: list[Hit] = []
    for i, result in enumerate(payload.get("results") or [], 1):
        hits.append(
            Hit(
                title=result.get("title") or "",
                url=result.get("url") or "",
                snippet=result.get("content") or result.get("snippet") or "",
                source=NAME,
                kind="organic",
                position=i,
                query=query,
            )
        )
    return hits


async def search(
    client: httpx.AsyncClient,
    query: str,
    num_results: int = 8,
    recency_days: Optional[int] = None,
) -> list[Hit]:
    if not enabled():
        raise RuntimeError("SEARXNG_URL is not configured")
    params: dict[str, Any] = {
        "q": query,
        "format": "json",
        "categories": "general",
    }
    resp = await client.get(
        f"{settings.searxng_url}/search",
        params=params,
        timeout=settings.search_provider_timeout,
    )
    resp.raise_for_status()
    hits = parse_searxng_payload(resp.json(), query=query)
    return hits[:num_results]
