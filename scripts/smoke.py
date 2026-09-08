#!/usr/bin/env python3
"""Live smoke against a running engine + router + one search key.

  ENGINE_URL=http://127.0.0.1:8090 ENGINE_API_KEY=... python scripts/smoke.py

Asserts:
  1. A dated factual question produces a web_search in the trace and a real URL
     in phoenician_sources.
  2. policy=off produces no tool calls.
"""
from __future__ import annotations

import os
import sys

import httpx


def _headers() -> dict[str, str]:
    key = os.getenv("ENGINE_API_KEY") or os.getenv("SEARCH_API_KEY") or ""
    if key:
        return {"Authorization": f"Bearer {key}"}
    return {}


def main() -> int:
    base = (os.getenv("ENGINE_URL") or "http://127.0.0.1:8090").rstrip("/")
    headers = _headers()
    with httpx.Client(timeout=180.0) as client:
        caps = client.get(f"{base}/capabilities", headers=headers)
        caps.raise_for_status()
        body = caps.json()
        print("capabilities:", body)
        if not body.get("brain_tool_calls_supported"):
            print(
                "WARNING: brain_tool_calls_supported is false — "
                "add the vLLM flags from the README before treating this as done.",
                file=sys.stderr,
            )

        dated = client.post(
            f"{base}/v1/chat/completions",
            headers=headers,
            json={
                "model": os.getenv("UPSTREAM_MODEL", "deepseek-v4-flash"),
                "messages": [
                    {
                        "role": "user",
                        "content": "What was Apple's most recently reported quarterly revenue? Cite a live URL.",
                    }
                ],
                "phoenician_web": {"policy": "required"},
            },
        )
        if dated.status_code == 424:
            print("FAIL: policy=required returned 424 (no successful search)", file=sys.stderr)
            print(dated.text, file=sys.stderr)
            return 1
        dated.raise_for_status()
        payload = dated.json()
        trace = payload.get("phoenician_tool_trace") or []
        sources = payload.get("phoenician_sources") or []
        print("trace:", trace)
        print("sources:", sources)
        tools = {t.get("tool") for t in trace}
        if "web_search" not in tools and "search_and_read" not in tools:
            print("FAIL: expected web_search or search_and_read in phoenician_tool_trace", file=sys.stderr)
            return 1
        urls = [s.get("url") or "" for s in sources]
        if not any(u.startswith("http") for u in urls):
            print("FAIL: expected a real URL in phoenician_sources", file=sys.stderr)
            return 1

        off = client.post(
            f"{base}/v1/chat/completions",
            headers=headers,
            json={
                "model": os.getenv("UPSTREAM_MODEL", "deepseek-v4-flash"),
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "phoenician_web": {"policy": "off"},
            },
        )
        off.raise_for_status()
        off_payload = off.json()
        if off_payload.get("phoenician_tool_trace"):
            print("FAIL: policy=off should not record tool calls", file=sys.stderr)
            return 1
        print("smoke ok")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
