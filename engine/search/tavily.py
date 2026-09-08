"""Tavily client — port of ai-router/app/tools/web_search.py."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings
from .base import Hit

logger = logging.getLogger("engine.search.tavily")

TAVILY_URL = "https://api.tavily.com/search"
NAME = "tavily"


def enabled() -> bool:
    return bool(settings.tavily_api_key)


def parse_tavily_payload(payload: dict[str, Any], query: str = "") -> list[Hit]:
    hits: list[Hit] = []
    for i, result in enumerate(payload.get("results") or [], 1):
        hits.append(
            Hit(
                title=result.get("title") or "",
                url=result.get("url") or "",
                snippet=result.get("content") or "",
                source=NAME,
                kind="organic",
                position=i,
                date=result.get("published_date"),
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
        raise RuntimeError("TAVILY_API_KEY is not configured")
    body: dict[str, Any] = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "max_results": num_results,
    }
    if recency_days:
        body["days"] = int(recency_days)
    resp = await client.post(
        TAVILY_URL,
        json=body,
        timeout=settings.search_provider_timeout,
    )
    resp.raise_for_status()
    return parse_tavily_payload(resp.json(), query=query)
