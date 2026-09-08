"""Health, metrics, and Brain tool-call capabilities."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ..config import VLLM_REQUIRED_FLAGS, settings
from ..runtime import capabilities
from ..search.merge import configured_providers

router = APIRouter()


def _search_ready() -> bool:
    return bool(configured_providers())


@router.get("/")
async def root() -> dict:
    """One-screen usage for humans and other engineers."""
    providers = configured_providers()
    return {
        "service": "local-engine-internet",
        "search_ready": _search_ready(),
        "providers": providers,
        "docs": "/docs",
        "try": {
            "search": (
                f"curl -s http://127.0.0.1:{settings.port}/v1/search "
                "-H 'Content-Type: application/json' "
                '-d \'{"query":"Phoenician Capital"}\''
            ),
            "compat": f"curl -s 'http://127.0.0.1:{settings.port}/search?q=Phoenician+Capital&num=5'",
            "fetch": (
                f"curl -s http://127.0.0.1:{settings.port}/v1/fetch "
                "-H 'Content-Type: application/json' "
                '-d \'{"url":"https://example.com"}\''
            ),
            "check": "python scripts/check_search.py",
        },
        "hint": (
            None
            if providers
            else "Set SERPAPI_KEY in .env and restart. That single key is enough to search."
        ),
    }


@router.get("/health")
async def health() -> dict:
    providers = configured_providers()
    return {
        "status": "ok",
        "search_ready": bool(providers),
        "upstream": settings.upstream_llm_base_url,
        "providers_configured": providers,
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
        "search_ready": _search_ready(),
        "tools": ["web_search", "fetch_url", "search_and_read"],
    }
