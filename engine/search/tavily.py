"""Tavily client — longer excerpts, independent of Google."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings
from .base import Hit
from .httputil import request_json

logger = logging.getLogger("engine.search.tavily")

TAVILY_URL = "https://api.tavily.com/search"
NAME = "tavily"


def enabled() -> bool:
    return bool(settings.tavily_api_key)


def parse_tavily_payload(payload: dict[str, Any], query: str = "") -> list[Hit]:
    hits: list[Hit] = []
    answer = payload.get("answer")
    if isinstance(answer, str) and answer.strip():
        hits.append(
            Hit(
                title="Tavily Answer",
                url="",
                snippet=answer.strip(),
                source=NAME,
                kind="answer_box",
                position=0,
                query=query,
            )
        )
    for i, result in enumerate(payload.get("results") or [], 1):
        hits.append(
            Hit(
                title=result.get("title") or "",
                url=result.get("url") or "",
                snippet=result.get("content") or result.get("raw_content") or "",
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
    depth = settings.tavily_search_depth if settings.tavily_search_depth in (
        "ultra-fast",
        "fast",
        "basic",
        "advanced",
    ) else "advanced"
    q = (query or "").strip()[:400]
    if not q:
        raise RuntimeError("Tavily query is empty")
    body: dict[str, Any] = {
        "api_key": settings.tavily_api_key,
        "query": q,
        "max_results": min(int(num_results), 20),
        "search_depth": depth,
        # We already have a Brain — Tavily's own guide says skip include_answer then.
        "include_answer": False,
        "topic": "general",
        "chunks_per_source": 5 if depth in ("advanced", "fast") else 3,
    }
    if recency_days:
        if recency_days <= 1:
            body["time_range"] = "day"
        elif recency_days <= 7:
            body["time_range"] = "week"
        elif recency_days <= 31:
            body["time_range"] = "month"
        else:
            body["time_range"] = "year"
    payload = await request_json(client, "POST", TAVILY_URL, json=body)
    err = payload.get("error") or payload.get("detail")
    if err:
        raise RuntimeError(str(err))
    return parse_tavily_payload(payload, query=query)
