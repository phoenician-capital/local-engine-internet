import json

import httpx
import pytest

from engine.agent.loop import LoopResult, run_agent_loop
from engine.errors import RequiredSearchFailed
from engine.tools.schemas import WEB_SEARCH_SCHEMA


def _assistant_tool_call(name: str, args: dict, call_id: str = "c1") -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _assistant_text(text: str) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 7, "total_tokens": 10},
    }


async def test_tool_round_then_final(monkeypatch):
    responses = [
        _assistant_tool_call("web_search", {"query": "acme revenue 2026"}),
        _assistant_text("Acme revenue was sourced."),
    ]

    async def _post(client, body, headers=None):
        return responses.pop(0)

    async def _search(*_a, **_k):
        return "Web search results for: acme\n\n[serpapi:organic]\n1. A\n   https://ir.acme.com"

    monkeypatch.setattr("engine.agent.loop.post_completion", _post)
    monkeypatch.setattr("engine.tools.execute.ToolExecutor.web_search", _search)

    async with httpx.AsyncClient() as client:
        result = await run_agent_loop(
            client,
            {
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "What is Acme revenue?"}],
                "phoenician_tools": ["web_search"],
            },
        )
    assert isinstance(result, LoopResult)
    assert result.trace[0]["tool"] == "web_search"
    assert result.response["choices"][0]["message"]["content"] == "Acme revenue was sourced."
    assert result.usage["total_tokens"] == 25


async def test_dsml_in_content_is_recovered(monkeypatch):
    dsml = (
        '<｜DSML｜invoke name="web_search">'
        '<｜DSML｜parameter name="query">acme</｜DSML｜parameter>'
        "</｜DSML｜invoke>"
    )
    responses = [
        {
            "choices": [{"message": {"role": "assistant", "content": dsml}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        _assistant_text("done"),
    ]

    async def _post(client, body, headers=None):
        return responses.pop(0)

    async def _search(self, query, num_results=None, recency_days=None):
        return f"hits for {query}"

    monkeypatch.setattr("engine.agent.loop.post_completion", _post)
    monkeypatch.setattr("engine.tools.execute.ToolExecutor.web_search", _search)

    async with httpx.AsyncClient() as client:
        result = await run_agent_loop(
            client,
            {"messages": [{"role": "user", "content": "q"}], "phoenician_tools": ["web_search"]},
        )
    assert result.trace[0]["arguments"]["query"] == "acme"


async def test_required_reask_then_424(monkeypatch):
    responses = [_assistant_text("I will not search."), _assistant_text("Still no.")]

    async def _post(client, body, headers=None):
        return responses.pop(0)

    monkeypatch.setattr("engine.agent.loop.post_completion", _post)
    async with httpx.AsyncClient() as client:
        with pytest.raises(RequiredSearchFailed):
            await run_agent_loop(
                client,
                {
                    "messages": [{"role": "user", "content": "today's price"}],
                    "phoenician_web": {"policy": "required"},
                    "phoenician_tools": ["web_search"],
                },
            )


async def test_required_reask_then_search_succeeds(monkeypatch):
    responses = [
        _assistant_text("thinking..."),
        _assistant_tool_call("web_search", {"query": "today"}),
        _assistant_text("Here is the sourced answer."),
    ]

    async def _post(client, body, headers=None):
        return responses.pop(0)

    async def _search(self, query, num_results=None, recency_days=None):
        self.search_succeeded = True
        self.sources.append({"title": "A", "url": "https://a.example", "date": None, "source": "serpapi"})
        return "hits"

    monkeypatch.setattr("engine.agent.loop.post_completion", _post)
    monkeypatch.setattr("engine.tools.execute.ToolExecutor.web_search", _search)

    async with httpx.AsyncClient() as client:
        result = await run_agent_loop(
            client,
            {
                "messages": [{"role": "user", "content": "q"}],
                "phoenician_web": {"policy": "required"},
                "phoenician_tools": ["web_search"],
            },
        )
    assert result.sources[0]["url"] == "https://a.example"
    assert "[PUBLIC_URL: https://a.example]" in result.citations
    assert "[SOURCE: Web Citation 1]" in result.citations


async def test_policy_off_passthrough(monkeypatch):
    called = {"n": 0}

    async def _post(client, body, headers=None):
        called["n"] += 1
        assert "tools" not in body
        return _assistant_text("no tools")

    monkeypatch.setattr("engine.agent.loop.post_completion", _post)
    async with httpx.AsyncClient() as client:
        result = await run_agent_loop(
            client,
            {
                "messages": [{"role": "user", "content": "hi"}],
                "phoenician_web": {"policy": "off"},
            },
        )
    assert called["n"] == 1
    assert result.trace == []


def test_schema_is_openai_function():
    assert WEB_SEARCH_SCHEMA["type"] == "function"
    assert WEB_SEARCH_SCHEMA["function"]["name"] == "web_search"
