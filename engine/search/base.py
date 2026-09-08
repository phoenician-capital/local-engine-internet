"""Shared Hit contract and search outcome."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional
from urllib.parse import urlparse, urlunparse

ProviderName = Literal["serpapi", "brave", "tavily", "searxng", "google_cse"]
HitKind = Literal["organic", "answer_box", "knowledge_graph", "related_question"]

ALL_PROVIDERS: tuple[str, ...] = ("serpapi", "brave", "tavily", "searxng", "google_cse")
# Fan-out order = blend order. Google fidelity first, then Tavily excerpts, then independent indexes.
DEFAULT_FANOUT: tuple[str, ...] = ("serpapi", "tavily", "brave", "searxng")
PROVIDER_PRIORITY: dict[str, int] = {
    "serpapi": 0,
    "tavily": 1,
    "brave": 2,
    "google_cse": 3,
    "searxng": 4,
}


@dataclass
class Hit:
    title: str
    url: str
    snippet: str
    source: str
    kind: str = "organic"
    position: int = 0
    date: Optional[str] = None
    query: str = ""
    also_from: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchOutcome:
    hits: list[Hit] = field(default_factory=list)
    providers_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_serpapi: Optional[dict[str, Any]] = None
    answer_box: Optional[dict[str, Any]] = None
    knowledge_graph: Optional[dict[str, Any]] = None
    related_questions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        """True only when every attempted provider raised — empty hits are OK."""
        return bool(self.errors) and not self.providers_used

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": [h.to_dict() for h in self.hits],
            "providers_used": list(self.providers_used),
            "errors": list(self.errors),
        }


def canonical_url(url: str) -> str:
    """Dedup key: scheme + host without www + path without trailing slash."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, host, path, "", "", ""))


def snippet_key(hit: Hit) -> str:
    snippet = (hit.snippet or "").strip()
    if snippet:
        return snippet[:120]
    return canonical_url(hit.url)
