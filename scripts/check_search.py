#!/usr/bin/env python3
"""Prove Mode 1 search works. One key (SERPAPI_KEY) is enough.

  python scripts/check_search.py           # prefer a running engine, else call SerpAPI directly
  python scripts/check_search.py --direct  # SerpAPI only (no server)
  python scripts/check_search.py --engine  # fail if the engine is not up

Does not print API keys. Does not need ai-router or a Brain.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

QUERY = "Phoenician Capital"
ENGINE_URL = (os.getenv("ENGINE_URL") or "http://127.0.0.1:8090").rstrip("/")


def _engine_headers() -> dict[str, str]:
    key = os.getenv("ENGINE_API_KEY") or os.getenv("SEARCH_API_KEY") or ""
    return {"Authorization": f"Bearer {key}"} if key else {}


def _has_any_search_key() -> bool:
    return bool(
        (os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY") or "").strip()
        or (os.getenv("TAVILY_API_KEY") or "").strip()
        or (os.getenv("BRAVE_API_KEY") or "").strip()
        or (os.getenv("SEARXNG_URL") or "").strip()
    )


def _summarize_hits(hits: list[dict]) -> None:
    print(f"  hits: {len(hits)}")
    for hit in hits[:5]:
        title = (hit.get("title") or "").replace("\n", " ")[:80]
        url = hit.get("url") or hit.get("link") or ""
        source = hit.get("source") or "serpapi"
        kind = hit.get("kind") or "organic"
        also = hit.get("also_from") or []
        extra = f"  [also {', '.join(also)}]" if also else ""
        print(f"  - [{source}:{kind}] {title}{extra}")
        if url:
            print(f"    {url}")


def check_via_engine() -> bool:
    headers = _engine_headers()
    try:
        with httpx.Client(timeout=20.0) as client:
            root = client.get(f"{ENGINE_URL}/", headers=headers)
            if root.status_code >= 400:
                print(f"engine {ENGINE_URL} returned HTTP {root.status_code}", file=sys.stderr)
                return False
            welcome = root.json()
            print(f"engine: {ENGINE_URL}")
            print(f"  search_ready: {welcome.get('search_ready')}")
            print(f"  providers: {welcome.get('providers')}")
            plugin = welcome.get("plugin") or {}
            if plugin:
                print(
                    f"  plugin: {plugin.get('enabled')}  "
                    f"intelligence={plugin.get('intelligence')}"
                )
            if welcome.get("hint"):
                print(f"  hint: {welcome['hint']}")
            if not welcome.get("search_ready"):
                if plugin.get("enabled") is False:
                    print(
                        "FAIL: internet plugin is disabled. Enable it at /ui "
                        'or POST /v1/plugin {"enabled": true}.',
                        file=sys.stderr,
                    )
                    return False
                print("FAIL: engine is up but no search provider is configured.", file=sys.stderr)
                print("      Set SERPAPI_KEY in .env and restart.", file=sys.stderr)
                return False

            search = client.post(
                f"{ENGINE_URL}/v1/search",
                headers=headers,
                json={"query": QUERY, "num_results": 8},
            )
            if search.status_code != 200:
                print(f"FAIL: POST /v1/search HTTP {search.status_code}", file=sys.stderr)
                print(search.text[:400], file=sys.stderr)
                return False
            body = search.json()
            print(
                f"POST /v1/search  query={QUERY!r}  "
                f"providers_used={body.get('providers_used')}  "
                f"confirmed={len(body.get('confirmed') or [])}"
            )
            _summarize_hits(body.get("hits") or [])
            if not body.get("hits"):
                print("FAIL: search returned zero hits", file=sys.stderr)
                return False

            compat = client.get(
                f"{ENGINE_URL}/search",
                headers=headers,
                params={"q": QUERY, "num": 5},
            )
            if compat.status_code != 200:
                print(f"FAIL: GET /search HTTP {compat.status_code}", file=sys.stderr)
                return False
            organic = (compat.json().get("organic_results") or [])
            print(f"GET /search     organic_results={len(organic)}")

            fetched = client.post(
                f"{ENGINE_URL}/v1/fetch",
                headers=headers,
                json={"url": "https://example.com", "mode": "httpx_only"},
            )
            if fetched.status_code != 200:
                print(f"FAIL: POST /v1/fetch HTTP {fetched.status_code}", file=sys.stderr)
                return False
            page = fetched.json()
            print(f"POST /v1/fetch  ok={page.get('ok')}  title={page.get('title')!r}")
            if not page.get("ok"):
                print(f"FAIL: fetch example.com failed: {page.get('error')}", file=sys.stderr)
                return False
            return True
    except httpx.ConnectError:
        return False


def check_direct() -> bool:
    if not _has_any_search_key():
        print(
            "FAIL: no search key. Set SERPAPI_KEY (enough alone), then TAVILY_API_KEY and BRAVE_API_KEY.",
            file=sys.stderr,
        )
        return False
    sys.path.insert(0, str(ROOT))
    from engine.config import settings
    from engine.search.merge import run_search

    settings.serpapi_key = (os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY") or settings.serpapi_key or "").strip()
    settings.tavily_api_key = (os.getenv("TAVILY_API_KEY") or settings.tavily_api_key or "").strip()
    settings.brave_api_key = (os.getenv("BRAVE_API_KEY") or settings.brave_api_key or "").strip()

    async def _run() -> int:
        async with httpx.AsyncClient() as client:
            outcome = await run_search(client, QUERY, num_results=8)
            print("direct mix (engine not required)")
            print(f"  providers_used: {outcome.providers_used}")
            _summarize_hits([h.to_dict() for h in outcome.hits])
            return len(outcome.hits)

    import asyncio

    try:
        n = asyncio.run(_run())
    except Exception as exc:
        print(f"FAIL: search failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False
    if n <= 0:
        print("FAIL: search returned zero hits", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that SerpAPI search works.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--direct", action="store_true", help="Call SerpAPI without a running engine")
    group.add_argument("--engine", action="store_true", help="Require a running engine on ENGINE_URL")
    args = parser.parse_args()

    if args.direct:
        ok = check_direct()
    elif args.engine:
        if _engine_unreachable():
            print(f"FAIL: no engine at {ENGINE_URL}. Start it with: python -m engine", file=sys.stderr)
            return 1
        ok = check_via_engine()
    else:
        ok = check_via_engine()
        if not ok:
            print(f"engine not reachable at {ENGINE_URL} — falling back to direct SerpAPI")
            ok = check_direct()

    if ok:
        print("check_search ok — Mode 1 search mix works")
        return 0
    return 1


def _engine_unreachable() -> bool:
    try:
        httpx.get(f"{ENGINE_URL}/health", timeout=2.0)
        return False
    except Exception:
        return True


if __name__ == "__main__":
    raise SystemExit(main())
