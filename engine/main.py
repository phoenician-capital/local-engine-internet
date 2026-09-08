"""Phoenician local-engine-internet.

Sits in front of ai-router. Mode 2 is an OpenAI-compatible chat-completions
loop that lets the local Brain decide when to search and fetch. Mode 1 is
raw /v1/search /v1/fetch /v1/research for pipelines that already decided.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import runtime
from .agent.loop import run_canary
from .api.chat import router as chat_router
from .api.compat import router as compat_router
from .api.health import router as health_router
from .api.openai_compat import router as openai_compat_router
from .api.primitives import router as primitives_router
from .auth import require_engine_key
from .config import VLLM_REQUIRED_FLAGS, settings
from .fetch.cache import FetchCache
from .search.merge import configured_providers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("engine")


async def _run_canary_safe() -> None:
    if runtime.http_client is None:
        return
    try:
        runtime.capabilities.update(await run_canary(runtime.http_client))
    except Exception as exc:
        runtime.capabilities["canary_error"] = f"{type(exc).__name__}: {exc}"
    if not runtime.capabilities.get("brain_tool_calls_supported"):
        logger.warning(
            "Brain tool-call canary failed (%s). Required vLLM flags: %s",
            runtime.capabilities.get("canary_error"),
            " ".join(VLLM_REQUIRED_FLAGS),
        )
    else:
        logger.info("Brain tool-call canary passed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    runtime.http_client = httpx.AsyncClient(
        headers={"User-Agent": "local-engine-internet/0.1"},
        follow_redirects=True,
        timeout=httpx.Timeout(settings.doc_fetch_timeout, read=settings.request_timeout),
    )
    runtime.fetch_cache = FetchCache(
        ttl_seconds=settings.fetch_cache_ttl,
        failure_ttl_seconds=settings.fetch_cache_failure_ttl,
    )
    providers = configured_providers()
    runtime.capabilities = {
        "brain_tool_calls_supported": False,
        "canary_error": "canary not run" if settings.run_canary_on_startup else "canary disabled",
        "providers": {name: True for name in providers},
    }
    logger.info(
        "local-engine-internet listening on %s:%d — upstream=%s providers=%s fetch_mode=%s",
        settings.host,
        settings.port,
        settings.upstream_llm_base_url,
        providers or ["(none — set SERPAPI_KEY)"],
        settings.fetch_mode,
    )
    if not providers:
        logger.warning("No search provider configured. Set SERPAPI_KEY in .env — that is enough to search.")
    canary_task = None
    if settings.run_canary_on_startup:
        # Do not block listen on a missing Brain (canary uses a short timeout).
        canary_task = asyncio.create_task(_run_canary_safe())
    yield
    if canary_task is not None:
        canary_task.cancel()
        try:
            await canary_task
        except (asyncio.CancelledError, Exception):
            pass
    if runtime.http_client is not None:
        await runtime.http_client.aclose()
        runtime.http_client = None


app = FastAPI(
    title="Phoenician local-engine-internet",
    version="0.1.0",
    lifespan=lifespan,
)

_cors = list(settings.cors_allowed_origins)
if not _cors and not settings.engine_api_key:
    # Local unauthenticated use — browser UIs (Open WebUI, etc.) can attach.
    _cors = ["*"]
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Priority"],
    )

_auth = [Depends(require_engine_key)]
app.include_router(health_router)
app.include_router(openai_compat_router)
app.include_router(chat_router, dependencies=_auth)
app.include_router(primitives_router, dependencies=_auth)
app.include_router(compat_router, dependencies=_auth)
