"""HTTP call to the upstream LLM (ai-router). Port of ai-router/app/http.py."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import settings

_DROP_HEADERS = {"host", "content-length", "authorization", "connection"}


def completions_url(base: str | None = None) -> str:
    root = (base or settings.upstream_llm_base_url).rstrip("/")
    parsed = urlparse(root)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        return root
    if path.endswith("/v1"):
        return f"{root}/chat/completions"
    return f"{root}/v1/chat/completions"


def auth_headers(incoming: dict[str, str]) -> dict[str, str]:
    headers = {k: v for k, v in incoming.items() if k.lower() not in _DROP_HEADERS}
    headers["content-type"] = "application/json"
    if settings.upstream_api_key:
        headers["authorization"] = f"Bearer {settings.upstream_api_key}"
    return headers


async def post_completion(
    client: httpx.AsyncClient,
    body: dict[str, Any],
    incoming_headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    headers = auth_headers(incoming_headers or {})
    # Forward X-Priority unchanged (ai-router reads it).
    resp = await client.post(
        completions_url(),
        json=body,
        headers=headers,
        timeout=timeout if timeout is not None else settings.request_timeout,
    )
    resp.raise_for_status()
    return resp.json()


EMPTY_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def extract_usage(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def add_usage(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {k: a.get(k, 0) + b.get(k, 0) for k in EMPTY_USAGE}
