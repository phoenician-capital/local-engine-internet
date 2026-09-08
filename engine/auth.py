"""Optional shared-secret auth for incoming requests.

Disabled (no-op) when ENGINE_API_KEY is unset — the expected state for local
development, matching ai-router. GET /search also accepts ``api_key=`` so
Earnings/EP/PI scrapers can drop in a SerpAPI-shaped URL.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, Query

from .config import settings


async def require_engine_key(
    authorization: Optional[str] = Header(default=None),
    api_key: Optional[str] = Query(default=None),
) -> None:
    if not settings.engine_api_key:
        return
    if authorization == f"Bearer {settings.engine_api_key}":
        return
    if api_key and api_key == settings.engine_api_key:
        return
    raise HTTPException(status_code=401, detail="Missing or invalid engine API key")
