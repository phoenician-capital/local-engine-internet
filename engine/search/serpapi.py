"""SerpAPI provider — full-field parse from EP smart_finder.py."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from ..config import settings
from .base import Hit
from .httputil import request_json
from .query import serpapi_tbs_for_recency

logger = logging.getLogger("engine.search.serpapi")

SERPAPI_URL = "https://serpapi.com/search"
NAME = "serpapi"

_pace_lock = asyncio.Lock()
_last_call_monotonic = 0.0


def enabled() -> bool:
    return bool(settings.serpapi_key)


def parse_serpapi_payload(payload: dict[str, Any], query: str = "") -> list[Hit]:
    """Parse organic + answer_box + knowledge_graph + related_questions[:2].

    Dedup of the *merged* list is merge.py's job. This parser only converts
    one SerpAPI JSON body into labeled Hits (EP smart_finder.py:584-638).
    """
    hits: list[Hit] = []
    seen_urls: set[str] = set()
    seen_snippets: set[str] = set()

    for result in payload.get("organic_results") or []:
        url = result.get("link") or ""
        snippet = result.get("snippet") or ""
        key = snippet[:120] if snippet else url
        if key in seen_snippets or url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        if key:
            seen_snippets.add(key)
        hits.append(
            Hit(
                title=result.get("title") or "",
                url=url,
                snippet=snippet,
                source=NAME,
                kind="organic",
                position=int(result.get("position") or 0),
                date=result.get("date"),
                query=query,
            )
        )

    answer_box = payload.get("answer_box") or {}
    if answer_box:
        answer_text = answer_box.get("answer") or answer_box.get("snippet") or ""
        if answer_text:
            hits.append(
                Hit(
                    title="Answer Box",
                    url=answer_box.get("link") or "",
                    snippet=answer_text,
                    source=NAME,
                    kind="answer_box",
                    position=0,
                    query=query,
                )
            )

    kg = payload.get("knowledge_graph") or {}
    if kg:
        parts = [kg.get("title") or "", kg.get("description") or ""]
        for attr in kg.get("attributes") or []:
            if isinstance(attr, dict):
                parts.append(str(attr.get("value") or ""))
            elif isinstance(attr, str):
                parts.append(attr)
        kg_text = " ".join(p for p in parts if p).strip()
        if kg_text:
            hits.append(
                Hit(
                    title=kg.get("title") or "Knowledge Graph",
                    url=kg.get("link") or "",
                    snippet=kg_text,
                    source=NAME,
                    kind="knowledge_graph",
                    position=0,
                    query=query,
                )
            )

    for i, result in enumerate((payload.get("news_results") or [])[:2], start=50):
        url = result.get("link") or ""
        snippet = result.get("snippet") or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        hits.append(
            Hit(
                title=result.get("title") or "",
                url=url,
                snippet=snippet,
                source=NAME,
                kind="organic",
                position=i,
                date=result.get("date"),
                query=query,
            )
        )

    for question in (payload.get("related_questions") or [])[:2]:
        q = question.get("question") or ""
        snippet = question.get("snippet") or ""
        q_text = f"{q} {snippet}".strip()
        if not q_text:
            continue
        hits.append(
            Hit(
                title=f"Related: {q[:60]}",
                url=question.get("link") or "",
                snippet=q_text,
                source=NAME,
                kind="related_question",
                position=0,
                query=query,
            )
        )

    return hits


def extras_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer_box": payload.get("answer_box") or None,
        "knowledge_graph": payload.get("knowledge_graph") or None,
        "related_questions": list((payload.get("related_questions") or [])[:2]),
    }


async def _pace() -> None:
    delay = float(settings.serpapi_pace_seconds or 0)
    if delay <= 0:
        return
    global _last_call_monotonic
    async with _pace_lock:
        now = time.monotonic()
        wait = delay - (now - _last_call_monotonic)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_monotonic = time.monotonic()


async def search(
    client: httpx.AsyncClient,
    query: str,
    num_results: int = 8,
    recency_days: Optional[int] = None,
) -> tuple[list[Hit], dict[str, Any]]:
    if not enabled():
        raise RuntimeError("SERPAPI_KEY is not configured")
    await _pace()
    params: dict[str, Any] = {
        "q": query,
        "api_key": settings.serpapi_key,
        "engine": "google",
        "hl": "en",
        "gl": "us",
        "num": num_results,
    }
    tbs = serpapi_tbs_for_recency(recency_days)
    if tbs:
        params["tbs"] = tbs
    payload = await request_json(client, "GET", SERPAPI_URL, params=params)
    err = payload.get("error")
    if err:
        raise RuntimeError(str(err))
    return parse_serpapi_payload(payload, query=query), extras_from_payload(payload)
