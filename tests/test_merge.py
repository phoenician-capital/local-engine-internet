import httpx
import respx
from httpx import Response

from engine.config import DomainMode, settings
from engine.errors import SearchUnavailable
from engine.search.base import Hit
from engine.search.merge import apply_domain_mode, dedup_hits, format_hits_for_model, run_search
from engine.search.serpapi import SERPAPI_URL


def test_dedup_by_canonical_url_and_snippet():
    hits = [
        Hit("A", "https://www.acme.com/page/", "same snippet here " * 10, "serpapi"),
        Hit("B", "https://acme.com/page", "other", "brave"),
        Hit("C", "https://other.com/x", "same snippet here " * 10, "tavily"),
    ]
    out = dedup_hits(hits)
    assert len(out) == 1
    assert out[0].source == "serpapi"


def test_ir_discovery_drops_sec_and_aggregators():
    hits = [
        Hit("SEC", "https://www.sec.gov/cgi-bin/browse", "filing", "serpapi"),
        Hit("IR", "https://ir.acme.com/q2", "results", "serpapi"),
        Hit("BBG", "https://www.bloomberg.com/news", "news", "brave"),
    ]
    kept = apply_domain_mode(hits, DomainMode.IR_DISCOVERY)
    assert [h.url for h in kept] == ["https://ir.acme.com/q2"]


def test_earnings_doc_allows_sec():
    hits = [Hit("SEC", "https://www.sec.gov/Archives/x.htm", "ex", "serpapi")]
    kept = apply_domain_mode(hits, DomainMode.EARNINGS_DOC)
    assert kept


def test_general_research_drops_social_only():
    hits = [
        Hit("FB", "https://facebook.com/acme", "s", "brave"),
        Hit("News", "https://reuters.com/article", "s", "brave"),
    ]
    kept = apply_domain_mode(hits, DomainMode.GENERAL_RESEARCH)
    assert [h.url for h in kept] == ["https://reuters.com/article"]


@respx.mock
async def test_all_providers_fail_raises():
    settings.serpapi_key = "k"
    respx.get(SERPAPI_URL).mock(return_value=Response(500))
    async with httpx.AsyncClient() as client:
        try:
            await run_search(client, "q")
            assert False, "expected SearchUnavailable"
        except SearchUnavailable as exc:
            assert "Do not present unverified facts" in exc.message
            assert "own knowledge" not in exc.message.lower()


@respx.mock
async def test_one_provider_failure_is_skipped():
    settings.serpapi_key = "s"
    settings.tavily_api_key = "t"
    respx.get(SERPAPI_URL).mock(return_value=Response(500))
    respx.post("https://api.tavily.com/search").mock(
        return_value=Response(
            200,
            json={"results": [{"title": "T", "content": "c", "url": "https://t.example"}]},
        )
    )
    async with httpx.AsyncClient() as client:
        outcome = await run_search(client, "q", num_results=5)
    assert outcome.providers_used == ["tavily"]
    assert outcome.hits[0].url == "https://t.example"
    text = format_hits_for_model("q", outcome)
    assert "https://t.example" in text
    assert "tavily" in text
