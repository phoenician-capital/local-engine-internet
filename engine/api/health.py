"""Health, metrics, and Brain tool-call capabilities."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ..config import VLLM_REQUIRED_FLAGS, settings
from ..runtime import capabilities
from ..search.merge import configured_providers

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "upstream": settings.upstream_llm_base_url,
        "providers_configured": configured_providers(),
        "fetch_mode": settings.fetch_mode,
    }


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/capabilities")
async def get_capabilities() -> dict:
    return {
        "status": "ok",
        "brain_tool_calls_supported": bool(capabilities.get("brain_tool_calls_supported")),
        "canary_error": capabilities.get("canary_error"),
        "canary_model": capabilities.get("canary_model"),
        "upstream": settings.upstream_llm_base_url,
        "fetch_mode": settings.fetch_mode,
        "providers": {
            name: name in set(configured_providers())
            for name in ("serpapi", "brave", "tavily", "searxng", "google_cse")
        },
        "vllm_required_flags": list(VLLM_REQUIRED_FLAGS),
        "tools": ["web_search", "fetch_url", "search_and_read"],
    }
