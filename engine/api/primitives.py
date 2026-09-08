"""Mode 1 primitives — code decides to search/fetch; the LLM is not in the loop."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..errors import SearchUnavailable
from ..fetch.ladder import fetch_url
from ..metrics import REQUESTS_TOTAL
from ..runtime import get_http_client
from ..search.merge import run_search

logger = logging.getLogger("engine.api.primitives")

router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    num_results: int = Field(default=8, ge=1, le=20)
    providers: Optional[list[str]] = None
    domain_mode: str = "general_research"
    recency_days: Optional[int] = None
    on_empty: str = "empty"

    @field_validator("query")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty")
        return value


class FetchRequest(BaseModel):
    url: str
    max_chars: Optional[int] = None
    mode: Optional[str] = None
    domain_mode: str = "general_research"


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    fetch_top: int = Field(default=3, ge=1, le=8)
    max_chars_per_page: int = Field(default=8000, ge=200, le=50_000)
    num_results: int = Field(default=8, ge=1, le=20)
    providers: Optional[list[str]] = None
    domain_mode: str = "general_research"
    recency_days: Optional[int] = None

    @field_validator("query")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty")
        return value


@router.post("/v1/search")
async def v1_search(req: SearchRequest) -> dict[str, Any]:
    client = get_http_client()
    try:
        outcome = await run_search(
            client,
            query=req.query,
            num_results=req.num_results,
            providers=req.providers,
            domain_mode=req.domain_mode,
            recency_days=req.recency_days,
            on_empty=req.on_empty,
        )
    except SearchUnavailable as exc:
        REQUESTS_TOTAL.labels(endpoint="search", status="502").inc()
        raise HTTPException(status_code=502, detail=exc.message) from exc
    REQUESTS_TOTAL.labels(endpoint="search", status="success").inc()
    return {
        "query": req.query,
        "hits": [h.to_dict() for h in outcome.hits],
        "providers_used": outcome.providers_used,
        "errors": outcome.errors,
    }


@router.post("/v1/fetch")
async def v1_fetch(req: FetchRequest) -> dict[str, Any]:
    client = get_http_client()
    page = await fetch_url(
        client,
        req.url,
        max_chars=req.max_chars,
        fetch_mode=req.mode,
        domain_mode=req.domain_mode,
    )
    REQUESTS_TOTAL.labels(endpoint="fetch", status="success" if page.ok else "error").inc()
    return page.to_dict()


@router.post("/v1/research")
async def v1_research(req: ResearchRequest) -> dict[str, Any]:
    client = get_http_client()
    try:
        outcome = await run_search(
            client,
            query=req.query,
            num_results=req.num_results,
            providers=req.providers,
            domain_mode=req.domain_mode,
            recency_days=req.recency_days,
        )
    except SearchUnavailable as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc

    urls: list[str] = []
    for hit in outcome.hits:
        if hit.url and hit.kind == "organic" and hit.url not in urls:
            urls.append(hit.url)
        if len(urls) >= req.fetch_top:
            break

    pages = await asyncio.gather(
        *[
            fetch_url(
                client,
                url,
                max_chars=req.max_chars_per_page,
                domain_mode=req.domain_mode,
            )
            for url in urls
        ]
    )
    REQUESTS_TOTAL.labels(endpoint="research", status="success").inc()
    return {
        "query": req.query,
        "hits": [h.to_dict() for h in outcome.hits],
        "providers_used": outcome.providers_used,
        "pages": [
            {
                "url": p.final_url or p.url,
                "title": p.title,
                "excerpt": p.text,
                "ok": p.ok,
                "is_pdf": p.is_pdf,
                "tier": p.tier,
                "error": p.error,
            }
            for p in pages
        ],
    }
