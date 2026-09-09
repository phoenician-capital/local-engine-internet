"""Dispatch tool calls to search / fetch. Never invent data on failure."""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from ..budget import ToolBudget
from ..config import DomainMode, FetchMode, settings
from ..errors import SearchUnavailable, fail_closed_budget, fail_closed_fetch, fail_closed_search
from ..fetch.ladder import Page, fetch_url
from ..search.base import Hit, SearchOutcome
from ..search.merge import format_hits_for_model, run_search
from .schemas import FETCH_URL_NAME, SEARCH_AND_READ_NAME, WEB_SEARCH_NAME

logger = logging.getLogger("engine.tools.execute")


def _opt_int(
    value: Any,
    default: Optional[int] = None,
    *,
    lo: Optional[int] = None,
    hi: Optional[int] = None,
) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def format_page_for_model(page: Page) -> str:
    header = f"[PUBLIC_URL: {page.final_url or page.url}]"
    if not page.ok:
        return f"{header}\n{fail_closed_fetch(page.error or 'fetch failed')}"
    title = f"Title: {page.title}\n" if page.title else ""
    meta = f"(fetched via {page.tier}; {'pdf' if page.is_pdf else 'html'})\n"
    return f"{header}\n{title}{meta}\n{page.text}".strip()


class ToolExecutor:
    def __init__(
        self,
        client: httpx.AsyncClient,
        budget: ToolBudget,
        fetch_mode: Optional[FetchMode] = None,
        domain_mode: DomainMode = DomainMode.GENERAL_RESEARCH,
        providers: Optional[list[str]] = None,
    ):
        self.client = client
        self.budget = budget
        self.fetch_mode = fetch_mode
        self.domain_mode = domain_mode
        self.providers = providers
        self.sources: list[dict[str, Any]] = []
        self.search_failed = False
        self.search_succeeded = False
        self.last_outcome: Optional[SearchOutcome] = None

    def _record_hits(self, hits: list[Hit]) -> None:
        seen = {(s.get("url") or "") for s in self.sources}
        for hit in hits:
            if not hit.url or hit.url in seen:
                continue
            seen.add(hit.url)
            self.sources.append(
                {
                    "title": hit.title,
                    "url": hit.url,
                    "date": hit.date,
                    "source": hit.source,
                    "kind": hit.kind,
                }
            )

    def _record_page(self, page: Page) -> None:
        url = page.final_url or page.url
        if not url or not page.ok:
            return
        if any(s.get("url") == url for s in self.sources):
            return
        self.sources.append(
            {
                "title": page.title,
                "url": url,
                "date": None,
                "source": f"fetch:{page.tier}",
                "kind": "page",
            }
        )

    async def web_search(
        self,
        query: str,
        num_results: Optional[int] = None,
        recency_days: Optional[int] = None,
    ) -> str:
        query = (query or "").strip()
        if not query:
            return fail_closed_search("query must not be empty")
        if not self.budget.allow_search():
            return fail_closed_budget("search", self.budget.max_search_uses)
        self.budget.note_search()
        n = _opt_int(num_results, settings.default_num_results, lo=1, hi=20) or settings.default_num_results
        try:
            outcome = await run_search(
                self.client,
                query=query,
                num_results=n,
                providers=self.providers,
                domain_mode=self.domain_mode,
                recency_days=recency_days,
            )
        except SearchUnavailable as exc:
            self.search_failed = True
            return str(exc.message)
        except Exception as exc:
            self.search_failed = True
            return fail_closed_search(str(exc))
        self.search_succeeded = True
        self.last_outcome = outcome
        self._record_hits(outcome.hits)
        return format_hits_for_model(query, outcome)

    async def fetch(self, url: str, max_chars: Optional[int] = None) -> str:
        if not self.budget.allow_fetch():
            return fail_closed_budget("fetch", self.budget.max_fetches)
        parsed = urlparse(url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return fail_closed_fetch("url must be an absolute http(s) URL")
        self.budget.note_fetch()
        page = await fetch_url(
            self.client,
            url,
            max_chars=_opt_int(max_chars, None, lo=200, hi=50_000),
            fetch_mode=self.fetch_mode,
            domain_mode=self.domain_mode,
        )
        self._record_page(page)
        return format_page_for_model(page)

    async def search_and_read(self, query: str, top_n: Optional[int] = None) -> str:
        query = (query or "").strip()
        if not query:
            return fail_closed_search("query must not be empty")
        n = _opt_int(top_n, settings.default_search_and_read_top_n, lo=1, hi=8) or settings.default_search_and_read_top_n
        search_text = await self.web_search(query)
        if search_text.startswith("ERROR:"):
            return search_text
        hits = list(self.last_outcome.hits if self.last_outcome else [])
        organics = [h for h in hits if h.url and h.kind == "organic"]
        organics.sort(key=lambda h: (0 if h.also_from else 1))
        urls: list[str] = []
        for hit in organics:
            if hit.url not in urls:
                urls.append(hit.url)
            if len(urls) >= n:
                break
        if not urls:
            return search_text + "\n\nNo fetchable organic URLs in the result set."
        excerpts: list[str] = []
        for url in urls:
            excerpts.append(await self.fetch(url))
        return search_text + "\n\n--- fetched pages ---\n\n" + "\n\n".join(excerpts)

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name == WEB_SEARCH_NAME:
            return await self.web_search(
                query=str(arguments.get("query") or ""),
                num_results=_opt_int(arguments.get("num_results"), lo=1, hi=20),
                recency_days=_opt_int(arguments.get("recency_days"), lo=1, hi=3650),
            )
        if name == FETCH_URL_NAME:
            return await self.fetch(
                url=str(arguments.get("url") or ""),
                max_chars=_opt_int(arguments.get("max_chars"), lo=200, hi=50_000),
            )
        if name == SEARCH_AND_READ_NAME:
            return await self.search_and_read(
                query=str(arguments.get("query") or ""),
                top_n=_opt_int(arguments.get("top_n"), lo=1, hi=8),
            )
        return f"ERROR: tool '{name}' is not available. Do not present unverified facts as sourced."
