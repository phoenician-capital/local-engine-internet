"""Environment-driven settings.

Read once at import time (same pattern as ai-router). Tests mutate the
``settings`` singleton in place rather than reloading from the environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

from dotenv import load_dotenv

load_dotenv()


class FetchMode(str, Enum):
    FULL = "full"
    NO_BROWSER = "no_browser"
    HTTPX_ONLY = "httpx_only"


class DomainMode(str, Enum):
    GENERAL_RESEARCH = "general_research"
    IR_DISCOVERY = "ir_discovery"
    EARNINGS_DOC = "earnings_doc"


class WebPolicy(str, Enum):
    AUTO = "auto"
    REQUIRED = "required"
    OFF = "off"


def _int_env(name: str, default: int) -> int:
    val = (os.getenv(name) or "").strip()
    return int(val) if val else default


def _float_env(name: str, default: float) -> float:
    val = (os.getenv(name) or "").strip()
    return float(val) if val else default


def _bool_env(name: str, default: bool) -> bool:
    val = (os.getenv(name) or "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def parse_fetch_mode(raw: str | None) -> FetchMode:
    mode = (raw or FetchMode.FULL.value).strip().lower()
    try:
        return FetchMode(mode)
    except ValueError:
        return FetchMode.NO_BROWSER


def parse_domain_mode(raw: str | None) -> DomainMode:
    mode = (raw or DomainMode.GENERAL_RESEARCH.value).strip().lower()
    try:
        return DomainMode(mode)
    except ValueError:
        return DomainMode.GENERAL_RESEARCH


def parse_web_policy(raw: str | None) -> WebPolicy:
    policy = (raw or WebPolicy.AUTO.value).strip().lower()
    try:
        return WebPolicy(policy)
    except ValueError:
        return WebPolicy.AUTO


@dataclass
class Settings:
    host: str = os.getenv("ENGINE_HOST", "0.0.0.0")
    port: int = int(os.getenv("ENGINE_PORT", "8090"))

    # Unset = open, same as ai-router's ROUTER_API_KEY. SEARCH_API_KEY is an alias.
    engine_api_key: str = (os.getenv("ENGINE_API_KEY") or os.getenv("SEARCH_API_KEY") or "")

    upstream_llm_base_url: str = (os.getenv("UPSTREAM_LLM_BASE_URL") or "http://127.0.0.1:8080").rstrip("/")
    upstream_api_key: str = (os.getenv("UPSTREAM_API_KEY") or os.getenv("ROUTER_API_KEY") or "")
    upstream_model: str = os.getenv("UPSTREAM_MODEL", "deepseek-v4-flash")

    serpapi_key: str = (os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY") or "")
    brave_api_key: str = os.getenv("BRAVE_API_KEY", "")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    searxng_url: str = (os.getenv("SEARXNG_URL") or "").rstrip("/")
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    google_search_engine_id: str = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "")
    tavily_search_depth: str = (os.getenv("TAVILY_SEARCH_DEPTH") or "advanced").strip().lower()
    search_provider_retries: int = _int_env("SEARCH_PROVIDER_RETRIES", 1)

    fetch_mode: str = os.getenv("FETCH_MODE", "full").lower()
    max_tool_rounds: int = _int_env("MAX_TOOL_ROUNDS", 6)
    max_search_uses: int = _int_env("MAX_SEARCH_USES", 8)
    max_fetches: int = _int_env("MAX_FETCHES", 8)
    web_context_budget_chars: int = _int_env("WEB_CONTEXT_BUDGET_CHARS", 150_000)
    max_chars_per_doc: int = _int_env("MAX_CHARS_PER_DOC", 8_000)
    max_chars_per_pdf: int = _int_env("MAX_CHARS_PER_PDF", 25_000)
    max_total_doc_chars: int = _int_env("MAX_TOTAL_DOC_CHARS", 50_000)
    max_pdf_bytes: int = _int_env("MAX_PDF_BYTES", 25 * 1024 * 1024)
    thin_html_char_threshold: int = _int_env("THIN_HTML_CHAR_THRESHOLD", 400)
    doc_fetch_timeout: float = _float_env("DOC_FETCH_TIMEOUT", 20.0)
    search_provider_timeout: float = _float_env("SEARCH_PROVIDER_TIMEOUT", 15.0)
    request_timeout: float = _float_env("REQUEST_TIMEOUT", 300.0)
    headless_render_timeout_ms: int = _int_env("HEADLESS_RENDER_TIMEOUT_MS", 15_000)
    serpapi_pace_seconds: float = _float_env("SERPAPI_PACE_SECONDS", 0.4)
    fetch_cache_ttl: float = _float_env("FETCH_CACHE_TTL", 1800.0)
    fetch_cache_failure_ttl: float = _float_env("FETCH_CACHE_FAILURE_TTL", 120.0)
    default_num_results: int = _int_env("DEFAULT_NUM_RESULTS", 8)
    default_search_and_read_top_n: int = _int_env("DEFAULT_SEARCH_AND_READ_TOP_N", 3)
    sec_user_agent: str = os.getenv(
        "SEC_EDGAR_USER_AGENT",
        "Mozilla/5.0 (compatible; LocalEngineInternet/1.0; +https://phoeniciancapital.com)",
    )
    default_domain_mode: str = os.getenv("DEFAULT_DOMAIN_MODE", "general_research")
    default_web_policy: str = os.getenv("DEFAULT_WEB_POLICY", "auto")
    run_canary_on_startup: bool = _bool_env("RUN_CANARY_ON_STARTUP", True)
    canary_timeout_seconds: float = _float_env("CANARY_TIMEOUT_SECONDS", 5.0)
    cors_allowed_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in (os.getenv("CORS_ALLOWED_ORIGINS") or "").split(",")
            if o.strip()
        ]
    )

    def resolved_fetch_mode(self) -> FetchMode:
        return parse_fetch_mode(self.fetch_mode)


settings = Settings()


VLLM_REQUIRED_FLAGS = (
    "--tokenizer-mode deepseek_v4",
    "--tool-call-parser deepseek_v4",
    "--enable-auto-tool-choice",
    "--reasoning-parser deepseek_v4",
)
