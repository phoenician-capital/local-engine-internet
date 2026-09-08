"""Mode 2 — OpenAI-compatible chat completions with an agentic tool loop."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..agent.loop import run_agent_loop
from ..agent.upstream import completions_url
from ..config import settings
from ..errors import RequiredSearchFailed
from ..metrics import ACTIVE_REQUESTS, REQUEST_LATENCY_SECONDS, REQUESTS_TOTAL
from ..runtime import get_http_client

logger = logging.getLogger("engine.api.chat")

router = APIRouter()


def _should_run_loop(body: dict[str, Any]) -> bool:
    web = body.get("phoenician_web") or {}
    policy = ""
    if isinstance(web, dict):
        policy = str(web.get("policy") or "").lower()
    if policy == "off":
        return False
    if body.get("phoenician_tools") == []:
        return False
    return True


async def _proxy_stream(request: Request, body: dict[str, Any]) -> StreamingResponse:
    client = get_http_client()
    headers = {k.lower(): v for k, v in request.headers.items()}
    from ..agent.upstream import auth_headers

    upstream_headers = auth_headers(headers)
    req = client.build_request(
        "POST",
        completions_url(),
        json=body,
        headers=upstream_headers,
        timeout=settings.request_timeout,
    )
    resp = await client.send(req, stream=True)
    if resp.status_code >= 400:
        await resp.aread()
        raise HTTPException(status_code=502, detail=f"Upstream LLM failed: HTTP {resp.status_code}")

    async def _iter():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()

    return StreamingResponse(
        _iter(),
        media_type=resp.headers.get("content-type", "text/event-stream"),
    )


async def _handle_chat(request: Request) -> JSONResponse | StreamingResponse:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be JSON")

    is_stream = bool(body.get("stream"))
    wants_loop = _should_run_loop(body)
    if is_stream and (wants_loop or body.get("phoenician_tools") or body.get("tools")):
        raise HTTPException(
            status_code=400,
            detail="stream:true and phoenician_tools cannot be combined yet — use one or the other.",
        )

    ACTIVE_REQUESTS.inc()
    start = time.perf_counter()
    status = "error"
    try:
        if is_stream:
            result = await _proxy_stream(request, body)
            status = "success"
            return result

        client = get_http_client()
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            loop = await run_agent_loop(client, body, headers)
        except RequiredSearchFailed as exc:
            REQUESTS_TOTAL.labels(endpoint="chat", status="424").inc()
            raise HTTPException(status_code=424, detail=exc.reason) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Upstream LLM failed: HTTP {exc.response.status_code}",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Upstream LLM unreachable: {exc}") from exc

        result = dict(loop.response)
        if loop.trace:
            result["phoenician_tool_trace"] = loop.trace
            result["phoenician_usage_total"] = loop.usage
        if loop.sources:
            result["phoenician_sources"] = loop.sources
        if loop.citations:
            result["phoenician_citations_block"] = loop.citations
        if loop.search_failed:
            result["phoenician_search_failed"] = True
        status = "success"
        return JSONResponse(result)
    finally:
        REQUEST_LATENCY_SECONDS.labels(endpoint="chat").observe(time.perf_counter() - start)
        REQUESTS_TOTAL.labels(endpoint="chat", status=status).inc()
        ACTIVE_REQUESTS.dec()


@router.post("/chat/completions")
async def chat_completions(request: Request):
    return await _handle_chat(request)


@router.post("/v1/chat/completions")
async def chat_completions_v1(request: Request):
    return await _handle_chat(request)
