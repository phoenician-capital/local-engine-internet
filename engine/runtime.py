"""Process-wide handles filled in during FastAPI lifespan."""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .fetch.cache import FetchCache

http_client: Optional[httpx.AsyncClient] = None
fetch_cache: Optional[FetchCache] = None
capabilities: dict[str, Any] = {
    "brain_tool_calls_supported": False,
    "canary_error": "canary not run",
    "providers": {},
}


def get_http_client() -> httpx.AsyncClient:
    if http_client is None:
        raise RuntimeError("HTTP client is not initialised — is the app lifespan running?")
    return http_client


def get_fetch_cache() -> FetchCache:
    if fetch_cache is None:
        raise RuntimeError("Fetch cache is not initialised — is the app lifespan running?")
    return fetch_cache
