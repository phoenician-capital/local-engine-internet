"""Mode 2 agentic tool loop in front of ai-router."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from ..budget import ToolBudget
from ..config import FetchMode, WebPolicy, parse_domain_mode, parse_fetch_mode, parse_web_policy, settings
from ..errors import RequiredSearchFailed
from ..metrics import TOOL_ROUNDS
from ..tools.dsml_fallback import recover_tool_calls
from ..tools.execute import ToolExecutor
from ..tools.schemas import DEFAULT_TOOLS, TOOL_SCHEMAS, WEB_SEARCH_NAME
from .citations import citations_block
from .prompts import FORCE_SEARCH_NUDGE, inject_system_guidance
from .upstream import add_usage, extract_usage, post_completion

logger = logging.getLogger("engine.agent.loop")

EXTENSION_KEYS = ("phoenician_tools", "phoenician_web")


@dataclass
class LoopResult:
    response: dict[str, Any]
    trace: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    citations: str = ""
    search_failed: bool = False
    rounds: int = 0


def _parse_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("tool call arguments were not valid JSON: %r", raw[:200])
        return {}


def _message_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls") or []
    if calls:
        return list(calls)
    recovered = recover_tool_calls(message.get("content"))
    if recovered:
        logger.info("recovered %d tool call(s) via DSML fallback", len(recovered))
        message["tool_calls"] = recovered
        # Strip markup so a later reader doesn't treat it as the answer.
        message["content"] = None
    return recovered


def _inject_tools(body: dict[str, Any], managed: list[str]) -> dict[str, Any]:
    existing = list(body.get("tools") or [])
    have = {t.get("function", {}).get("name") for t in existing}
    for name in managed:
        if name not in have and name in TOOL_SCHEMAS:
            existing.append(TOOL_SCHEMAS[name])
    body["tools"] = existing
    body.setdefault("tool_choice", "auto")
    return body


def _strip_extensions(body: dict[str, Any]) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    body = dict(body)
    raw_tools = body.pop("phoenician_tools", None)
    web = body.pop("phoenician_web", None) or {}
    if not isinstance(web, dict):
        web = {}
    if raw_tools is None:
        managed = list(DEFAULT_TOOLS)
    else:
        managed = [t for t in raw_tools if t in TOOL_SCHEMAS]
    return body, managed, web


async def run_agent_loop(
    client: httpx.AsyncClient,
    body: dict[str, Any],
    headers: Optional[dict[str, str]] = None,
) -> LoopResult:
    body, managed, web = _strip_extensions(body)
    policy = parse_web_policy(web.get("policy") or settings.default_web_policy)
    headers = headers or {}

    if policy is WebPolicy.OFF or not managed:
        # Pure pass-through — no tool injection, no guidance.
        response = await post_completion(client, body, headers)
        return LoopResult(response=response, usage=extract_usage(response))

    domain_mode = parse_domain_mode(web.get("domain_mode") or settings.default_domain_mode)
    fetch_mode: Optional[FetchMode] = None
    if web.get("fetch_mode"):
        fetch_mode = parse_fetch_mode(web.get("fetch_mode"))
    providers = web.get("providers")
    if providers is not None and not isinstance(providers, list):
        providers = None

    budget = ToolBudget.from_web_options(web)
    executor = ToolExecutor(
        client,
        budget,
        fetch_mode=fetch_mode,
        domain_mode=domain_mode,
        providers=providers,
    )

    body = _inject_tools(body, managed)
    messages = inject_system_guidance(list(body.get("messages") or []))
    body["messages"] = messages
    body.setdefault("model", settings.upstream_model)
    body["stream"] = False

    response = await post_completion(client, body, headers)
    total_usage = extract_usage(response)
    trace: list[dict[str, Any]] = []
    rounds = 0
    forced_reask = False

    while rounds < budget.max_rounds:
        choice = (response.get("choices") or [{}])[0]
        message = dict(choice.get("message") or {})
        tool_calls = _message_tool_calls(message)

        if not tool_calls:
            if policy is WebPolicy.REQUIRED and not forced_reask and not executor.search_succeeded:
                forced_reask = True
                logger.info("policy=required and no tool call — forcing web_search re-ask")
                messages.append(message if message.get("role") else {"role": "assistant", "content": message.get("content")})
                messages.append({"role": "user", "content": FORCE_SEARCH_NUDGE})
                body = {
                    **body,
                    "messages": messages,
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": WEB_SEARCH_NAME},
                    },
                }
                response = await post_completion(client, body, headers)
                total_usage = add_usage(total_usage, extract_usage(response))
                continue
            break

        # Clear forced tool_choice after the model actually called a tool.
        body["tool_choice"] = "auto"
        messages.append(message)

        async def _run_one(call: dict[str, Any]) -> tuple[dict[str, Any], str]:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args = _parse_args(fn.get("arguments"))
            if name in managed:
                result = await executor.execute(name, args)
            else:
                result = f"ERROR: tool '{name}' is not available. Do not present unverified facts as sourced."
            return call, result

        executed = await asyncio.gather(*(_run_one(c) for c in tool_calls))
        for call, result in executed:
            fn = call.get("function") or {}
            args = _parse_args(fn.get("arguments"))
            trace.append({"tool": fn.get("name"), "arguments": args})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or "",
                    "content": result,
                }
            )

        budget.trim_tool_messages(messages)
        body = {**body, "messages": messages}
        response = await post_completion(client, body, headers)
        total_usage = add_usage(total_usage, extract_usage(response))
        rounds += 1
        TOOL_ROUNDS.inc()

    if policy is WebPolicy.REQUIRED and not executor.search_succeeded:
        reason = "model did not perform a successful web_search"
        if executor.search_failed:
            reason = "web_search was required but every provider failed"
        raise RequiredSearchFailed(reason)

    return LoopResult(
        response=response,
        trace=trace,
        usage=total_usage,
        sources=executor.sources,
        citations=citations_block(executor.sources),
        search_failed=executor.search_failed,
        rounds=rounds,
    )


async def run_canary(client: httpx.AsyncClient) -> dict[str, Any]:
    """Tiny tool-enabled prompt. Reports whether the Brain emits tool_calls."""
    body = {
        "model": settings.upstream_model,
        "messages": [
            {"role": "system", "content": "You must call the web_search tool. Do not answer in prose."},
            {"role": "user", "content": "Call web_search with query 'phoenician capital'."},
        ],
        "tools": [TOOL_SCHEMAS[WEB_SEARCH_NAME]],
        "tool_choice": {"type": "function", "function": {"name": WEB_SEARCH_NAME}},
        "max_tokens": 256,
        "stream": False,
    }
    try:
        response = await post_completion(
            client, body, {}, timeout=settings.canary_timeout_seconds
        )
    except Exception as exc:
        return {
            "brain_tool_calls_supported": False,
            "canary_error": f"{type(exc).__name__}: {exc}",
        }
    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    calls = message.get("tool_calls") or recover_tool_calls(message.get("content"))
    supported = bool(calls)
    return {
        "brain_tool_calls_supported": supported,
        "canary_error": None if supported else "upstream returned no tool_calls (check vLLM flags)",
        "canary_model": response.get("model") or settings.upstream_model,
    }
