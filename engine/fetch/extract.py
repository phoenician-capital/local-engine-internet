"""HTML → text: Trafilatura first, Earnings html_to_text fallback."""
from __future__ import annotations

import logging
import re
from typing import Optional

from .urlutil import extract_canonical, extract_title

logger = logging.getLogger("engine.fetch.extract")

try:
    import trafilatura
    from trafilatura.settings import use_config

    _TRAFILATURA = True
    _TRAF_CONFIG = use_config()
    _TRAF_CONFIG.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
except Exception:  # pragma: no cover - optional
    trafilatura = None  # type: ignore[assignment]
    _TRAFILATURA = False
    _TRAF_CONFIG = None


def html_to_text(html: str) -> str:
    """Port of Earnings HTMLCleaner.html_to_text."""
    if not html:
        return ""

    html = re.sub(r"(?is)<(script|style|noscript|svg|head).*?</\1>", " ", html)
    html = re.sub(r"(?i)<(br|/p|/div|/li|/tr|/h[1-6])\s*>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)

    for a, b in (
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
        ("&euro;", "€"),
        ("&pound;", "£"),
        ("&yen;", "¥"),
    ):
        text = text.replace(a, b)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    text = re.sub(
        r"Cookie Policy|Privacy Policy|Terms of Service|Terms and Conditions|"
        r"Accept Cookies|Close|×|Skip to content",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def extract_html(
    html: str,
    url: str = "",
    max_chars: Optional[int] = None,
) -> tuple[str, str, str]:
    """Return ``(text, title, canonical_url)``.

    Trafilatura markdown when it yields substance; otherwise Earnings fallback.
    """
    title = ""
    canonical = url
    text = ""

    if _TRAFILATURA and html:
        try:
            extracted = trafilatura.extract(
                html,
                url=url or None,
                output_format="markdown",
                include_links=True,
                include_tables=True,
                config=_TRAF_CONFIG,
            )
            meta = trafilatura.extract_metadata(html, default_url=url or None)
            if extracted:
                text = extracted
            if meta:
                title = getattr(meta, "title", None) or ""
                canonical = getattr(meta, "url", None) or url
        except Exception as exc:
            logger.debug("trafilatura failed for %s: %s", url[:80], exc)

    if not text:
        text = html_to_text(html)
    if not title:
        title = extract_title(html)
    if not canonical or canonical == url:
        canonical = extract_canonical(html, fallback=url) or url

    if max_chars is not None and max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text, title, canonical
