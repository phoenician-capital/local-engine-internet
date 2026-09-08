import httpx

from engine.errors import FAIL_CLOSED_SUFFIX, fail_closed_search
from engine.search.merge import run_search
from engine.errors import SearchUnavailable
from engine.tools.execute import ToolExecutor
from engine.budget import ToolBudget
from engine.config import DomainMode


async def test_no_providers_never_says_own_knowledge():
    async with httpx.AsyncClient() as client:
        try:
            await run_search(client, "anything")
            assert False
        except SearchUnavailable as exc:
            msg = exc.message
    assert "own knowledge" not in msg.lower()
    assert FAIL_CLOSED_SUFFIX in msg
    assert "ERROR: web_search unavailable" in msg


async def test_over_budget_is_error_string():
    budget = ToolBudget(max_search_uses=0, max_fetches=0, max_rounds=1, web_context_chars=100)
    async with httpx.AsyncClient() as client:
        ex = ToolExecutor(client, budget, domain_mode=DomainMode.GENERAL_RESEARCH)
        out = await ex.web_search("q")
    assert out.startswith("ERROR:")
    assert "own knowledge" not in out.lower()


def test_fail_closed_helper_wording():
    text = fail_closed_search("serpapi 500")
    assert "serpapi 500" in text
    assert "Do not present unverified facts as sourced." in text
