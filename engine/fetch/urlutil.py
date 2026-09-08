"""Small URL helpers ported from Earnings summary/utils.py."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

_SKIP_HREF_SUBSTR = (
    "mailto:",
    "javascript:",
    "tel:",
    "cookie-policy",
    "cookie_policy",
    "cookiepolicy",
    "privacy-policy",
    "terms-of",
    "terms-and-conditions",
    "facebook.com",
    "twitter.com",
    "x.com/",
    "linkedin.com",
    "youtube.com",
    "instagram.com",
)

_ANCHOR_RE = re.compile(
    r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def resolve_href(href: str, base_url: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
        scheme = parsed.scheme or "https"
        return f"{scheme}:{href}"
    if href.startswith("/"):
        parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
        return f"{parsed.scheme or 'https'}://{parsed.netloc}{href}"
    return urljoin(base_url, href)


def is_pdf_url(url: str) -> bool:
    if not url:
        return False
    lowered = url.lower().split("?")[0]
    return lowered.endswith(".pdf") or "filetype=pdf" in url.lower()


def extract_all_links(html: str, base_url: str) -> list[dict[str, str]]:
    if not html:
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, inner in _ANCHOR_RE.findall(html):
        if any(s in href.lower() for s in _SKIP_HREF_SUBSTR):
            continue
        if href.startswith("#"):
            continue
        try:
            absolute = resolve_href(href, base_url)
        except Exception:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        out.append({"href": absolute, "url": absolute, "text": text})
    return out


def absolutize_html_links(html: str, base_url: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        href = match.group(1)
        try:
            abs_url = resolve_href(href, base_url)
        except Exception:
            return match.group(0)
        return match.group(0).replace(href, abs_url, 1)

    return re.sub(r'href=["\']([^"\']+)["\']', _repl, html, flags=re.IGNORECASE)


def extract_title(html: str) -> str:
    if not html:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", text).strip()


def extract_canonical(html: str, fallback: str = "") -> str:
    if not html:
        return fallback
    m = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
        html,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
            html,
            re.IGNORECASE,
        )
    return (m.group(1).strip() if m else "") or fallback


def looks_like_html_url(url: str) -> bool:
    path = (url or "").lower().split("?")[0]
    return path.endswith(".htm") or path.endswith(".html") or "htm" in path
