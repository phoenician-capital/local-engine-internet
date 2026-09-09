"""Mode 2 — OpenAI-compatible chat completions with an agentic tool loop."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import runtime
from ..agent.loop import run_agent_loop, strip_engine_tools, strip_extension_keys
from ..agent.upstream import completions_url
from ..config import WebPolicy, settings
from ..errors import RequiredSearchFailed
from ..metrics import ACTIVE_REQUESTS, REQUEST_LATENCY_SECONDS, REQUESTS_TOTAL
from ..plugin import intelligence_policy, plugin_enabled, plugin_status
from ..runtime import get_http_client

logger = logging.getLogger("engine.api.chat")

router = APIRouter()


def _web_options(body: dict[str, Any]) -> dict[str, Any]:
    web = body.get("phoenician_web") or {}
    return web if isinstance(web, dict) else {}


def _should_run_loop(body: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
    """Layer 1 off, or layer 2 off / empty tools → pass-through."""
    web = _web_options(body)
    if intelligence_policy(web, headers) is WebPolicy.OFF:
        return False
    if body.get("phoenician_tools") == []:
        return False
    return True


def _outbound_chat_body(body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Never forward phoenician_* extras. Strip our tools when the plugin is off."""
    outbound = strip_extension_keys(body)
    if not plugin_enabled(_web_options(body), headers):
        outbound = strip_engine_tools(outbound)
    return outbound


def _upstream_down_detail(exc: Exception) -> str:
    search_bit = (
        "Search still works at POST /v1/search. "
        if runtime.plugin_enabled
        else "Internet plugin is disabled (enable it at /ui). "
    )
    return (
        f"Upstream LLM unreachable ({exc}). {search_bit}"
        "Set UPSTREAM_LLM_BASE_URL (default http://127.0.0.1:8080) for chat."
    )


async def _proxy_stream(request: Request, body: dict[str, Any]) -> StreamingResponse:
    client = get_http_client()
    headers = {k.lower(): v for k, v in request.headers.items()}
    from ..agent.upstream import auth_headers

    upstream_headers = auth_headers(headers)
    req = client.build_request(
        "POST",
        completions_url(),
        json=_outbound_chat_body(body, headers),
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

    headers = {k.lower(): v for k, v in request.headers.items()}
    is_stream = bool(body.get("stream"))
    wants_loop = _should_run_loop(body, headers)
    if is_stream and wants_loop:
        raise HTTPException(
            status_code=400,
            detail="stream:true and the internet plugin cannot be combined yet — disable the plugin or set phoenician_web.policy to off.",
        )

    ACTIVE_REQUESTS.inc()
    start = time.perf_counter()
    status = "error"
    try:
        if is_stream:
            try:
                result = await _proxy_stream(request, body)
            except httpx.RequestError as exc:
                raise HTTPException(status_code=502, detail=_upstream_down_detail(exc)) from exc
            status = "success"
            return result

        client = get_http_client()
        try:
            loop = await run_agent_loop(client, body, headers)
        except RequiredSearchFailed as exc:
            REQUESTS_TOTAL.labels(endpoint="chat", status="424").inc()
            raise HTTPException(status_code=424, detail=exc.reason) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Upstream LLM failed: HTTP {exc.response.status_code}. "
                    "Point UPSTREAM_LLM_BASE_URL at ai-router or any OpenAI-compatible host."
                ),
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=_upstream_down_detail(exc)) from exc

        result = dict(loop.response)
        result["phoenician_plugin"] = {
            **plugin_status(_web_options(body), headers),
            "searched": bool(loop.trace or loop.sources),
            "intelligence": loop.intelligence,
            "enabled": loop.plugin_enabled,
        }
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
