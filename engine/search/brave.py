"""Brave Search API — independent, cheap, good default fan-out partner."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings
from .base import Hit
from .query import brave_freshness

logger = logging.getLogger("engine.search.brave")

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
NAME = "brave"


def enabled() -> bool:
    return bool(settings.brave_api_key)


def parse_brave_payload(payload: dict[str, Any], query: str = "") -> list[Hit]:
    web = (payload.get("web") or {}).get("results") or []
    hits: list[Hit] = []
    for i, result in enumerate(web, 1):
        hits.append(
            Hit(
                title=result.get("title") or "",
                url=result.get("url") or "",
                snippet=result.get("description") or "",
                source=NAME,
                kind="organic",
                position=i,
                date=result.get("age") or result.get("page_age"),
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
        raise RuntimeError("BRAVE_API_KEY is not configured")
    params: dict[str, Any] = {"q": query, "count": min(int(num_results), 20)}
    freshness = brave_freshness(recency_days)
    if freshness:
        params["freshness"] = freshness
    resp = await client.get(
        BRAVE_URL,
        params=params,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": settings.brave_api_key,
        },
        timeout=settings.search_provider_timeout,
    )
    resp.raise_for_status()
    return parse_brave_payload(resp.json(), query=query)
