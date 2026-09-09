"""Two-layer internet plugin.

Layer 1 — enabled / disabled. Master switch. When off, no search, no fetch,
no tools. Chat is a plain pass-through to the upstream LLM.

Layer 2 — intelligence (only when layer 1 is on). The model decides mid-answer
whether this question needs the live web (``policy: auto``). Research callers
can still force a search with ``policy: required``.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from . import runtime
from .config import WebPolicy, parse_web_policy, settings


def _header_override(headers: Optional[dict[str, str]]) -> Optional[bool]:
    if not headers:
        return None
    raw = ""
    for key, value in headers.items():
        if key.lower() == "x-phoenician-plugin":
            raw = str(value).strip().lower()
            break
    if raw in ("off", "0", "false", "disabled"):
        return False
    if raw in ("on", "1", "true", "enabled"):
        return True
    return None


def _body_override(web: Optional[dict[str, Any]]) -> Optional[bool]:
    if not web or "enabled" not in web:
        return None
    val = web.get("enabled")
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return bool(val)


def plugin_enabled(
    web: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
) -> bool:
    """Layer 1. Global off always wins — a request cannot force the plugin on."""
    if not runtime.plugin_enabled:
        return False
    header = _header_override(headers)
    if header is False:
        return False
    body = _body_override(web)
    if body is False:
        return False
    return True


def intelligence_policy(
    web: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
) -> WebPolicy:
    """Layer 2. Meaningless when the plugin is off."""
    if not plugin_enabled(web, headers):
        return WebPolicy.OFF
    raw = (web or {}).get("policy") or settings.default_web_policy
    return parse_web_policy(str(raw) if raw is not None else None)


def plugin_status(
    web: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    on = plugin_enabled(web, headers)
    policy = intelligence_policy(web, headers)
    return {
        "enabled": on,
        "intelligence": policy.value if on else "off",
        "global_enabled": bool(runtime.plugin_enabled),
        "layers": {
            "1_master": "enabled" if on else "disabled",
            "2_intelligence": policy.value if on else "off",
        },
        "explain": {
            "1": "enabled or disabled — master switch",
            "2": "when enabled, the model decides whether this question needs the live web",
        },
    }


def require_plugin_enabled(headers: Optional[dict[str, str]] = None) -> None:
    if plugin_enabled(headers=headers):
        return
    raise HTTPException(
        status_code=503,
        detail="Internet plugin is disabled. Enable it at /ui or POST /v1/plugin {\"enabled\": true}.",
    )
