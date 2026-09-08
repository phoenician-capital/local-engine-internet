"""Brave Search API — independent index, news + extra snippets."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings
from .base import Hit
from .httputil import request_json
from .query import brave_freshness

logger = logging.getLogger("engine.search.brave")

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
NAME = "brave"


def enabled() -> bool:
    return bool(settings.brave_api_key)


def _snippet(result: dict[str, Any]) -> str:
    parts = [result.get("description") or ""]
    extras = result.get("extra_snippets") or []
    if isinstance(extras, list):
        parts.extend(str(x) for x in extras if x)
    return " ".join(p for p in parts if p).strip()


def parse_brave_payload(payload: dict[str, Any], query: str = "") -> list[Hit]:
    hits: list[Hit] = []
    seen: set[str] = set()
    web = (payload.get("web") or {}).get("results") or []
    for i, result in enumerate(web, 1):
        url = result.get("url") or ""
        if url:
            seen.add(url)
        hits.append(
            Hit(
                title=result.get("title") or "",
                url=url,
                snippet=_snippet(result),
                source=NAME,
                kind="organic",
                position=i,
                date=result.get("age") or result.get("page_age"),
                query=query,
            )
        )
    news = (payload.get("news") or {}).get("results") or []
    for i, result in enumerate(news[:2], start=40):
        url = result.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        hits.append(
            Hit(
                title=result.get("title") or "",
                url=url,
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
    params: dict[str, Any] = {
        "q": query,
        "count": min(int(num_results), 20),
        "extra_snippets": "true",
        "text_decorations": "false",
        "safesearch": "off",
    }
    freshness = brave_freshness(recency_days)
    if freshness:
        params["freshness"] = freshness
    payload = await request_json(
        client,
        "GET",
        BRAVE_URL,
        params=params,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": settings.brave_api_key,
        },
    )
    err = payload.get("error") or payload.get("message")
    if err and not (payload.get("web") or {}).get("results"):
        raise RuntimeError(str(err))
    return parse_brave_payload(payload, query=query)
