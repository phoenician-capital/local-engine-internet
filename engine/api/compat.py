"""SerpAPI-shaped GET /search so Earnings/EP/PI scrapers can switch by URL."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ..errors import SearchUnavailable
from ..plugin import require_plugin_enabled
from ..runtime import get_http_client
from ..search.base import SearchOutcome
from ..search.merge import run_search

router = APIRouter()


def hits_to_serpapi_shape(outcome: SearchOutcome) -> dict[str, Any]:
    """Build ``organic_results`` / ``answer_box`` / ``knowledge_graph`` / related."""
    organic = []
    for hit in outcome.hits:
        if hit.kind != "organic":
            continue
        organic.append(
            {
                "title": hit.title,
                "snippet": hit.snippet,
                "link": hit.url,
                "position": hit.position or len(organic) + 1,
            }
        )

    payload: dict[str, Any] = {"organic_results": organic}

    if outcome.answer_box:
        payload["answer_box"] = outcome.answer_box
    else:
        box = next((h for h in outcome.hits if h.kind == "answer_box"), None)
        if box:
            payload["answer_box"] = {
                "answer": box.snippet,
                "snippet": box.snippet,
                "link": box.url,
            }

    if outcome.knowledge_graph:
        payload["knowledge_graph"] = outcome.knowledge_graph
    else:
        kg = next((h for h in outcome.hits if h.kind == "knowledge_graph"), None)
        if kg:
            payload["knowledge_graph"] = {
                "title": kg.title,
                "description": kg.snippet,
                "link": kg.url,
            }

    if outcome.related_questions:
        payload["related_questions"] = outcome.related_questions
    else:
        related = [h for h in outcome.hits if h.kind == "related_question"]
        if related:
            payload["related_questions"] = [
                {"question": h.title.replace("Related: ", "", 1), "snippet": h.snippet, "link": h.url}
                for h in related
            ]
    return payload


@router.get("/search")
async def serpapi_compat(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    engine: str = Query("google"),
    num: int = Query(10, ge=1, le=20),
    api_key: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    del engine, api_key  # accepted for drop-in compatibility; auth is elsewhere
    require_plugin_enabled(dict(request.headers))
    client = get_http_client()
    # Pin SerpAPI when configured so answer_box / KG survive for Earnings/EP.
    from ..search.merge import configured_providers

    configured = configured_providers()
    pin = ["serpapi"] if "serpapi" in configured else None
    try:
        outcome = await run_search(
            client,
            query=q,
            num_results=num,
            providers=pin,
        )
    except SearchUnavailable as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc
    return hits_to_serpapi_shape(outcome)
