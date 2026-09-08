"""Perplexity-shaped citation blocks PI writers already parse."""
from __future__ import annotations

from typing import Any


def citations_block(sources: list[dict[str, Any]]) -> str:
    """Emit both ``citations`` and ``search_results`` forms from PI web_search.py.

    1. ``[SOURCE: Web Citation N]`` + ``[PUBLIC_URL: url]``
    2. ``[SOURCE: {title} (Date: {date})]`` + ``[PUBLIC_URL: url]``
    """
    if not sources:
        return ""
    numbered: list[str] = ["Citations (use these URLs for hyperlinks):"]
    detailed: list[str] = ["Detailed Sources (use these URLs for hyperlinks):"]
    n = 0
    for src in sources:
        url = (src.get("url") or "").strip()
        if not url:
            continue
        n += 1
        numbered.append(f"[SOURCE: Web Citation {n}]")
        numbered.append(f"[PUBLIC_URL: {url}]")
        numbered.append("")
        title = src.get("title") or "No title"
        date = src.get("date") or "No date"
        detailed.append(f"[SOURCE: {title} (Date: {date})]")
        detailed.append(f"[PUBLIC_URL: {url}]")
        detailed.append("")
    if n == 0:
        return ""
    return "\n".join(numbered).rstrip() + "\n\n" + "\n".join(detailed).rstrip() + "\n"
