"""Optional self-hosted SearXNG provider."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings
from .base import Hit
from .httputil import request_json

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
        "language": "en",
    }
    if recency_days:
        if recency_days <= 1:
            params["time_range"] = "day"
        elif recency_days <= 7:
            params["time_range"] = "week"
        elif recency_days <= 31:
            params["time_range"] = "month"
        else:
            params["time_range"] = "year"
    payload = await request_json(
        client,
        "GET",
        f"{settings.searxng_url}/search",
        params=params,
    )
    hits = parse_searxng_payload(payload, query=query)
    return hits[:num_results]
