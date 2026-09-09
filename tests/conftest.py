from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine import runtime
from engine.config import settings
from engine.fetch.ladder import _PROCESS_CACHE


@pytest.fixture(autouse=True)
def _reset_settings():
    original = {
        "engine_api_key": settings.engine_api_key,
        "serpapi_key": settings.serpapi_key,
        "brave_api_key": settings.brave_api_key,
        "tavily_api_key": settings.tavily_api_key,
        "searxng_url": settings.searxng_url,
        "google_api_key": settings.google_api_key,
        "google_search_engine_id": settings.google_search_engine_id,
        "upstream_llm_base_url": settings.upstream_llm_base_url,
        "upstream_api_key": settings.upstream_api_key,
        "fetch_mode": settings.fetch_mode,
        "serpapi_pace_seconds": settings.serpapi_pace_seconds,
        "run_canary_on_startup": settings.run_canary_on_startup,
        "thin_html_char_threshold": settings.thin_html_char_threshold,
        "max_search_uses": settings.max_search_uses,
        "max_fetches": settings.max_fetches,
        "max_tool_rounds": settings.max_tool_rounds,
        "web_context_budget_chars": settings.web_context_budget_chars,
        "search_provider_retries": settings.search_provider_retries,
        "tavily_search_depth": settings.tavily_search_depth,
        "plugin_enabled": settings.plugin_enabled,
        "default_web_policy": settings.default_web_policy,
    }
    settings.engine_api_key = ""
    settings.serpapi_key = ""
    settings.brave_api_key = ""
    settings.tavily_api_key = ""
    settings.searxng_url = ""
    settings.google_api_key = ""
    settings.google_search_engine_id = ""
    settings.upstream_llm_base_url = "http://upstream.test"
    settings.upstream_api_key = "upstream-key"
    settings.fetch_mode = "no_browser"
    settings.serpapi_pace_seconds = 0.0
    settings.run_canary_on_startup = False
    settings.thin_html_char_threshold = 400
    settings.search_provider_retries = 0
    settings.tavily_search_depth = "basic"
    settings.plugin_enabled = True
    settings.default_web_policy = "auto"
    original_runtime_plugin = runtime.plugin_enabled
    runtime.plugin_enabled = True
    _PROCESS_CACHE.clear()
    yield
    for key, value in original.items():
        setattr(settings, key, value)
    runtime.plugin_enabled = original_runtime_plugin
    _PROCESS_CACHE.clear()


@pytest.fixture
def client():
    from engine.main import app

    with TestClient(app) as c:
        yield c
