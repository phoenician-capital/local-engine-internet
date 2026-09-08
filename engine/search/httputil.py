"""Shared JSON HTTP with one cheap retry — skip the provider after that."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from ..config import settings

_RETRY_STATUSES = frozenset({429, 500, 502, 503})


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    timeout: Optional[float] = None,
    **kwargs: Any,
) -> Any:
    attempts = max(1, 1 + int(settings.search_provider_retries))
    last_error: Exception | None = None
    wait = 0.35
    for i in range(attempts):
        try:
            resp = await client.request(
                method,
                url,
                timeout=timeout if timeout is not None else settings.search_provider_timeout,
                **kwargs,
            )
            if resp.status_code in _RETRY_STATUSES and i + 1 < attempts:
                await asyncio.sleep(wait * (i + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            last_error = exc
            if i + 1 < attempts:
                await asyncio.sleep(wait * (i + 1))
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError(f"{method} {url} failed")
