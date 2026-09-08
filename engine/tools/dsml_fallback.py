"""Recover DeepSeek tool calls when vLLM leaves them in ``content``.

Streaming / long-context Flash sometimes emits DSML invoke blocks or
``tool_calls_begin`` markup instead of structured ``tool_calls``. The
agent loop runs this when ``tool_calls`` is empty.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

# DeepSeek uses a fullwidth bar (｜) in DSML tokens; ASCII | also appears.
_B = r"[|｜]"
_DSML_INVOKE_RE = re.compile(
    rf"<{_B}?DSML{_B}?invoke\s+name=\"([^\"]+)\"[^>]*>(.*?)</{_B}?DSML{_B}?invoke>",
    re.IGNORECASE | re.DOTALL,
)
_DSML_PARAM_RE = re.compile(
    rf"<{_B}?DSML{_B}?parameter\s+name=\"([^\"]+)\"[^>]*>(.*?)</{_B}?DSML{_B}?parameter>",
    re.IGNORECASE | re.DOTALL,
)
_DSML_INVOKE_OPEN_RE = re.compile(
    rf"<{_B}?DSML{_B}?invoke\s+name=\"([^\"]+)\"[^>]*>",
    re.IGNORECASE,
)
_DSML_PARAM_LOOSE_RE = re.compile(
    rf"<{_B}?DSML{_B}?parameter\s+name=\"([^\"]+)\"[^>]*>(.*?)(?:</{_B}?DSML{_B}?parameter>|$)",
    re.IGNORECASE | re.DOTALL,
)

# DeepSeek V3/V4 tokenizer tool-call markup
_TOOL_CALL_BLOCK_RE = re.compile(
    r"<\|tool▁calls▁begin\|>(.*?)<\|tool▁calls▁end\|>",
    re.DOTALL,
)
_TOOL_CALL_ONE_RE = re.compile(
    r"<\|tool▁call▁begin\|>(.*?)<\|tool▁call▁end\|>",
    re.DOTALL,
)
_TOOL_SEP_RE = re.compile(
    r"(?:function)?\s*<\|tool▁sep\|>\s*([A-Za-z0-9_]+)\s*(.*)",
    re.DOTALL,
)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)

KNOWN = {"web_search", "fetch_url", "search_and_read"}


def _new_id() -> str:
    return f"dsml_{uuid.uuid4().hex[:12]}"


def _tool_call(name: str, arguments: dict[str, Any], call_id: str | None = None) -> dict[str, Any]:
    return {
        "id": call_id or _new_id(),
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


def _parse_json_blob(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    fenced = _JSON_FENCE_RE.search(raw)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    obj = _JSON_OBJECT_RE.search(raw)
    if obj:
        try:
            parsed = json.loads(obj.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}


def _params_from_dsml(block: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for match in _DSML_PARAM_RE.finditer(block):
        params[match.group(1).strip()] = match.group(2).strip()
    if params:
        return params
    for match in _DSML_PARAM_LOOSE_RE.finditer(block):
        params[match.group(1).strip()] = match.group(2).strip()
    if not params:
        # Last resort: the block itself is the query for web_search.
        cleaned = re.sub(r"<[^>]+>", " ", block).strip()
        if cleaned:
            params["query"] = cleaned
    return params


def recover_tool_calls(content: str | None) -> list[dict[str, Any]]:
    """Return OpenAI-shaped tool_calls recovered from model text, or []."""
    if not content or not isinstance(content, str):
        return []
    calls: list[dict[str, Any]] = []

    for match in _DSML_INVOKE_RE.finditer(content):
        name = match.group(1).strip()
        if name not in KNOWN:
            continue
        args = _params_from_dsml(match.group(2))
        if name == "web_search" and "query" not in args and args:
            args = {"query": next(iter(args.values()))}
        calls.append(_tool_call(name, args))

    if not calls:
        # Open invoke without a closer (start-token omission / truncation).
        opens = list(_DSML_INVOKE_OPEN_RE.finditer(content))
        for i, match in enumerate(opens):
            name = match.group(1).strip()
            if name not in KNOWN:
                continue
            start = match.end()
            end = opens[i + 1].start() if i + 1 < len(opens) else len(content)
            args = _params_from_dsml(content[start:end])
            if name == "web_search" and "query" not in args and args:
                args = {"query": next(iter(args.values()))}
            if args:
                calls.append(_tool_call(name, args))

    for block in _TOOL_CALL_BLOCK_RE.findall(content):
        for one in _TOOL_CALL_ONE_RE.findall(block):
            sep = _TOOL_SEP_RE.search(one)
            if not sep:
                # "function\nweb_search\n{json}"
                lines = [ln.strip() for ln in one.strip().splitlines() if ln.strip()]
                name = next((ln for ln in lines if ln in KNOWN), "")
                blob = one
            else:
                name = sep.group(1).strip()
                blob = sep.group(2)
            if name not in KNOWN:
                continue
            args = _parse_json_blob(blob)
            if name == "web_search" and "query" not in args:
                continue
            calls.append(_tool_call(name, args))

    # Dedup identical (name, arguments)
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for call in calls:
        key = (call["function"]["name"], call["function"]["arguments"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(call)
    return unique
