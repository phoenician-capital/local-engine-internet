"""Google Programmable Search — PI official-website fallback."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings
from .base import Hit
from .httputil import request_json

logger = logging.getLogger("engine.search.google_cse")

CSE_URL = "https://www.googleapis.com/customsearch/v1"
NAME = "google_cse"


def enabled() -> bool:
    return bool(settings.google_api_key and settings.google_search_engine_id)


def parse_cse_payload(payload: dict[str, Any], query: str = "") -> list[Hit]:
    hits: list[Hit] = []
    for i, item in enumerate(payload.get("items") or [], 1):
        hits.append(
            Hit(
                title=item.get("title") or "",
                url=item.get("link") or "",
                snippet=item.get("snippet") or "",
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
        raise RuntimeError("GOOGLE_API_KEY + GOOGLE_SEARCH_ENGINE_ID are not configured")
    payload = await request_json(
        client,
        "GET",
        CSE_URL,
        timeout=max(settings.search_provider_timeout, 20.0),
        params={
            "key": settings.google_api_key,
            "cx": settings.google_search_engine_id,
            "q": query,
            "num": min(int(num_results), 10),
        },
    )
    err = payload.get("error")
    if err:
        message = err.get("message") if isinstance(err, dict) else err
        raise RuntimeError(str(message))
    return parse_cse_payload(payload, query=query)
