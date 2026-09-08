"""Fan-out, dedup, and per-mode domain filtering."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from ..config import DomainMode, parse_domain_mode, settings
from ..errors import SearchUnavailable, fail_closed_search
from ..fetch.policy import host_denied
from ..metrics import SEARCH_TOTAL
from . import brave, google_cse, searxng, serpapi, tavily
from .base import (
    ALL_PROVIDERS,
    DEFAULT_FANOUT,
    Hit,
    SearchOutcome,
    canonical_url,
    snippet_key,
)

logger = logging.getLogger("engine.search.merge")

_MODULES = {
    "serpapi": serpapi,
    "brave": brave,
    "tavily": tavily,
    "searxng": searxng,
    "google_cse": google_cse,
}


def configured_providers() -> list[str]:
    return [name for name, mod in _MODULES.items() if mod.enabled()]


def resolve_providers(requested: Optional[list[str]]) -> list[str]:
    configured = set(configured_providers())
    if requested:
        wanted = [p for p in requested if p in ALL_PROVIDERS]
        unknown = [p for p in requested if p not in ALL_PROVIDERS]
        if unknown:
            logger.warning("unknown search providers requested: %s", unknown)
        pinned = [p for p in wanted if p in configured]
        return pinned
    # CSE is pin-only (official-site fallback), not part of the default fan-out.
    return [p for p in DEFAULT_FANOUT if p in configured]


def dedup_hits(hits: list[Hit]) -> list[Hit]:
    """Dedup by canonical URL then snippet[:120]. Keep first (source stays visible)."""
    out: list[Hit] = []
    seen_urls: set[str] = set()
    seen_snippets: set[str] = set()
    for hit in hits:
        url_key = canonical_url(hit.url) if hit.url else ""
        snip = snippet_key(hit)
        if url_key and url_key in seen_urls:
            continue
        if snip and snip in seen_snippets:
            continue
        if url_key:
            seen_urls.add(url_key)
        if snip:
            seen_snippets.add(snip)
        out.append(hit)
    return out


def apply_domain_mode(hits: list[Hit], domain_mode: DomainMode) -> list[Hit]:
    kept: list[Hit] = []
    for hit in hits:
        denied, reason = host_denied(hit.url, domain_mode)
        if denied:
            logger.debug("dropping hit %s (%s)", hit.url, reason)
            continue
        kept.append(hit)
    return kept


async def _call_provider(
    client: httpx.AsyncClient,
    name: str,
    query: str,
    num_results: int,
    recency_days: Optional[int],
) -> tuple[str, list[Hit], dict[str, Any]]:
    mod = _MODULES[name]
    extras: dict[str, Any] = {}
    try:
        if name == "serpapi":
            hits, extras = await serpapi.search(client, query, num_results, recency_days)
        else:
            hits = await mod.search(client, query, num_results, recency_days)
        SEARCH_TOTAL.labels(provider=name, status="ok").inc()
        return name, hits, extras
    except Exception as exc:
        SEARCH_TOTAL.labels(provider=name, status="error").inc()
        raise RuntimeError(f"{name}: {exc}") from exc


async def run_search(
    client: httpx.AsyncClient,
    query: str,
    num_results: int = 8,
    providers: Optional[list[str]] = None,
    domain_mode: str | DomainMode = DomainMode.GENERAL_RESEARCH,
    recency_days: Optional[int] = None,
    on_empty: str = "empty",
) -> SearchOutcome:
    """Fan-out to configured providers. Provider failure is skipped; all-fail errors."""
    mode = domain_mode if isinstance(domain_mode, DomainMode) else parse_domain_mode(str(domain_mode))
    names = resolve_providers(providers)
    if not names:
        raise SearchUnavailable(
            fail_closed_search(
                "no search provider configured: set SERPAPI_KEY, BRAVE_API_KEY, "
                "TAVILY_API_KEY, or SEARXNG_URL"
            )
        )

    tasks = [
        _call_provider(client, name, query, num_results, recency_days) for name in names
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    outcome = SearchOutcome()
    collected: list[Hit] = []
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            logger.warning("search provider %s failed for query=%r: %s", name, query, result)
            outcome.errors.append(f"{name}: failed ({result})")
            continue
        _n, hits, extras = result
        outcome.providers_used.append(name)
        collected.extend(hits)
        if name == "serpapi":
            outcome.raw_serpapi = extras
            outcome.answer_box = extras.get("answer_box")
            outcome.knowledge_graph = extras.get("knowledge_graph")
            outcome.related_questions = extras.get("related_questions") or []

    if not outcome.providers_used:
        raise SearchUnavailable(
            fail_closed_search(f"every configured provider failed for: {query}")
        )

    merged = apply_domain_mode(dedup_hits(collected), mode)
    outcome.hits = merged[: max(int(num_results), 1) * 4] if merged else []
    # Keep extra kinds even if we cap organics — answer_box / KG are small and useful.
    # Re-slice more carefully: take organics up to num_results, always keep specials.
    organics = [h for h in merged if h.kind == "organic"][:num_results]
    specials = [h for h in merged if h.kind != "organic"]
    outcome.hits = organics + specials

    if not outcome.hits and on_empty == "error":
        raise SearchUnavailable(fail_closed_search(f"no hits for: {query}"))
    return outcome


def format_hits_for_model(query: str, outcome: SearchOutcome) -> str:
    """Labeled blocks the model weighs itself — sources stay visible."""
    if not outcome.hits:
        extra = ""
        if outcome.errors:
            extra = " Partial provider errors: " + "; ".join(outcome.errors)
        return f"Web search results for: {query}\n\nNo results.{extra}".strip()

    lines = [f"Web search results for: {query}", ""]
    if outcome.errors:
        lines.append("Provider warnings: " + "; ".join(outcome.errors))
        lines.append("")
    by_source: dict[str, list[Hit]] = {}
    for hit in outcome.hits:
        by_source.setdefault(f"{hit.source}:{hit.kind}", []).append(hit)
    for label, group in by_source.items():
        lines.append(f"[{label}]")
        for i, hit in enumerate(group, 1):
            date = f" ({hit.date})" if hit.date else ""
            lines.append(f"{i}. {hit.title}{date}")
            if hit.snippet:
                lines.append(f"   {hit.snippet}")
            if hit.url:
                lines.append(f"   {hit.url}")
        lines.append("")
    return "\n".join(lines).strip()
