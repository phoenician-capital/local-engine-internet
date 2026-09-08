"""Fan-out, dedup, and per-mode domain filtering."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from ..config import DomainMode, parse_domain_mode
from ..errors import SearchUnavailable, fail_closed_search
from ..fetch.policy import host_denied
from ..metrics import SEARCH_TOTAL
from . import brave, google_cse, searxng, serpapi, tavily
from .base import (
    ALL_PROVIDERS,
    DEFAULT_FANOUT,
    PROVIDER_PRIORITY,
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
        if wanted and not pinned:
            raise SearchUnavailable(
                fail_closed_search(
                    f"requested providers {wanted} are not configured "
                    f"(configured: {sorted(configured) or 'none'})"
                )
            )
        if requested and not wanted:
            raise SearchUnavailable(
                fail_closed_search(
                    f"unknown search providers: {unknown}; known: {list(ALL_PROVIDERS)}"
                )
            )
        return pinned
    # CSE is pin-only (official-site fallback), not part of the default fan-out.
    return [p for p in DEFAULT_FANOUT if p in configured]


def _merge_organic(a: Hit, b: Hit) -> Hit:
    """Same URL from two providers: keep Google as source, take the longer snippet."""
    ra = PROVIDER_PRIORITY.get(a.source, 50)
    rb = PROVIDER_PRIORITY.get(b.source, 50)
    primary, other = (a, b) if ra <= rb else (b, a)
    snippet = primary.snippet or ""
    other_snip = other.snippet or ""
    if len(other_snip) >= len(snippet) + 40:
        snippet = other_snip
    also: list[str] = []
    for src in list(primary.also_from) + [other.source] + list(other.also_from):
        if src and src != primary.source and src not in also:
            also.append(src)
    return Hit(
        title=primary.title or other.title,
        url=primary.url or other.url,
        snippet=snippet,
        source=primary.source,
        kind="organic",
        position=primary.position or other.position,
        date=primary.date or other.date,
        query=primary.query or other.query,
        also_from=also,
    )


def collapse_organics(hits: list[Hit]) -> list[Hit]:
    """Merge duplicate organic URLs; leave answer_box / KG / related intact."""
    by_url: dict[str, Hit] = {}
    no_url: list[Hit] = []
    specials: list[Hit] = []
    for hit in hits:
        if hit.kind != "organic":
            specials.append(hit)
            continue
        key = canonical_url(hit.url) if hit.url else ""
        if not key:
            no_url.append(hit)
            continue
        existing = by_url.get(key)
        by_url[key] = _merge_organic(existing, hit) if existing else hit
    return list(by_url.values()) + no_url + specials


def dedup_hits(hits: list[Hit]) -> list[Hit]:
    """Collapse same-URL organics, then drop near-identical snippets."""
    collapsed = collapse_organics(hits)
    out: list[Hit] = []
    seen_urls: set[str] = set()
    seen_snippets: set[str] = set()
    for hit in collapsed:
        url_key = canonical_url(hit.url) if hit.url else ""
        snip = snippet_key(hit)
        if hit.kind == "organic":
            if url_key and url_key in seen_urls:
                continue
            if snip and snip in seen_snippets:
                continue
        else:
            special_key = f"{hit.kind}:{url_key or snip}"
            if special_key in seen_snippets:
                continue
            seen_snippets.add(special_key)
        if url_key and hit.kind == "organic":
            seen_urls.add(url_key)
        if snip and hit.kind == "organic":
            seen_snippets.add(snip)
        out.append(hit)
    return out


def blend_organics(organics: list[Hit], num_results: int) -> list[Hit]:
    """Round-robin across providers. Cross-confirmed URLs go first."""
    limit = max(int(num_results), 1)
    if not organics:
        return []

    confirmed: dict[str, list[Hit]] = {}
    unique: dict[str, list[Hit]] = {}
    for hit in organics:
        bucket = confirmed if hit.also_from else unique
        bucket.setdefault(hit.source, []).append(hit)
    for group in list(confirmed.values()) + list(unique.values()):
        group.sort(key=lambda h: h.position or 99)

    def _rr(pools: dict[str, list[Hit]], room: int) -> list[Hit]:
        if room <= 0:
            return []
        order = [p for p in DEFAULT_FANOUT if pools.get(p)]
        order.extend(p for p in pools if p not in order and pools[p])
        picked: list[Hit] = []
        i = 0
        while len(picked) < room and any(pools[p] for p in order):
            src = order[i % len(order)]
            i += 1
            if not pools[src]:
                continue
            picked.append(pools[src].pop(0))
        return picked

    out = _rr(confirmed, limit)
    if len(out) < limit:
        out.extend(_rr(unique, limit - len(out)))
    return out[:limit]


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
    organics = blend_organics([h for h in merged if h.kind == "organic"], num_results)
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
            also = f"  [also {', '.join(hit.also_from)}]" if hit.also_from else ""
            lines.append(f"{i}. {hit.title}{date}{also}")
            if hit.snippet:
                lines.append(f"   {hit.snippet}")
            if hit.url:
                lines.append(f"   {hit.url}")
        lines.append("")
    return "\n".join(lines).strip()
