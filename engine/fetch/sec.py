"""SEC EDGAR exhibit discovery — port of Earnings sec_handler.py (no LLM ranker)."""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from ..config import settings
from .extract import html_to_text
from .pdf import pdf_parser
from .policy import DEFAULT_HEADERS
from .urlutil import extract_all_links, looks_like_html_url

logger = logging.getLogger("engine.fetch.sec")

SEC_USER_AGENT_DEFAULT = (
    "Mozilla/5.0 (compatible; EarningsTracker/1.0; +https://phoeniciancapital.com)"
)


def sec_headers() -> dict[str, str]:
    headers = dict(DEFAULT_HEADERS)
    headers["User-Agent"] = settings.sec_user_agent or SEC_USER_AGENT_DEFAULT
    headers["Accept"] = (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    )
    return headers


def extract_sec_exhibit_urls(html: str, base_url: str) -> list[str]:
    if not html:
        return []

    exhibit_urls: list[str] = []
    patterns = [
        r'href=["\']([^"\']*ex-99-1[^"\']*\.htm[^"\']*)["\']',
        r'href=["\']([^"\']*ex99-1[^"\']*\.htm[^"\']*)["\']',
        r'href=["\']([^"\']*ex-99-2[^"\']*\.htm[^"\']*)["\']',
        r'href=["\']([^"\']*ex99-2[^"\']*\.htm[^"\']*)["\']',
        r'href=["\']([^"\']*ex-99-1[^"\']*\.pdf[^"\']*)["\']',
        r'href=["\']([^"\']*ex99-1[^"\']*\.pdf[^"\']*)["\']',
        r'href=["\']([^"\']*ex-\d+-\d+[^"\']*)["\']',
        r'href=["\']([^"\']*exhibit[\d\-]+[^"\']*)["\']',
        r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?EX-99\.1.*?</a>',
        r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?EX-99-1.*?</a>',
    ]

    for pattern in patterns:
        for match in re.findall(pattern, html, re.IGNORECASE | re.DOTALL):
            match = match.strip().strip('"').strip("'")
            if not match:
                continue
            if match.startswith("//"):
                scheme = urlparse(base_url).scheme or "https"
                full_url = f"{scheme}:{match}"
            elif match.startswith("/"):
                parsed = urlparse(base_url)
                full_url = f"{parsed.scheme}://{parsed.netloc}{match}"
            elif match.startswith("http"):
                full_url = match
            else:
                full_url = urljoin(base_url, match)
            if full_url not in exhibit_urls:
                exhibit_urls.append(full_url)

    def _priority(url: str) -> tuple[int, int]:
        url_lower = url.lower()
        is_pdf = 0 if url_lower.endswith(".pdf") else 1
        is_ex991 = 0 if ("ex-99-1" in url_lower or "ex99-1" in url_lower) else 1
        return (is_pdf, is_ex991)

    exhibit_urls.sort(key=_priority)
    return exhibit_urls


def extract_exhibit_from_wrapper(html: str) -> Optional[str]:
    if not html:
        return None
    patterns = [
        r"<DOCUMENT>.*?<TYPE>EX-99\.1.*?<TEXT>(.*?)</TEXT>.*?</DOCUMENT>",
        r"<DOCUMENT>.*?<TYPE>EX-99-1.*?<TEXT>(.*?)</TEXT>.*?</DOCUMENT>",
        r"<DOCUMENT>.*?<TYPE>6-K.*?<TEXT>(.*?)</TEXT>.*?</DOCUMENT>",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            content = match.group(1)
            content = content.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            content = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", content, flags=re.DOTALL)
            return content
    return None


def extract_sec_html_content(html: str) -> Optional[str]:
    if not html:
        return None
    patterns = [
        r'<div[^>]*id="documentContent"[^>]*>(.*?)</div>',
        r'<div[^>]*class="body"[^>]*>(.*?)</div>',
        r'<div[^>]*id="content"[^>]*>(.*?)</div>',
        r'<div[^>]*class="content"[^>]*>(.*?)</div>',
        r"<body[^>]*>(.*?)</body>",
    ]
    content = None
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            content = match.group(1)
            test_text = html_to_text(content)
            if len(test_text) > 200:
                break
    if not content:
        content = html
    text = html_to_text(content)
    boilerplate = [
        r"(Page \d+ of \d+|Filing Fee|Filer|SEC \d+-\d+).*$",
        r"(This document was filed with the SEC|The information contained in this report)",
        r"(sec\.gov|www\.sec\.gov)",
        r"(CIK|SIC|State of Inc|IRS EIN)",
    ]
    for pattern in boilerplate:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text and len(text) > 100 else None


def extract_yahoo_finance_exhibit_urls(content: str, base_url: str) -> list[dict[str, str]]:
    if not content:
        return []
    base_host = urlparse(base_url).netloc.lower()
    base_path = base_url.rsplit("/", 1)[0]
    wrapper_norm = base_url.split("?")[0].rstrip("/")
    priority_keywords = (
        "earnings release",
        "press release",
        "results",
        "earnings presentation",
        "investor presentation",
        "presentation",
        "financial statements",
        "6-k",
        "exhibit",
    )
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in extract_all_links(content, base_url):
        href = link.get("href") or ""
        if not href.startswith("http"):
            continue
        href_norm = href.split("?")[0].rstrip("/")
        if href_norm == wrapper_norm or href_norm in seen:
            continue
        if urlparse(href).netloc.lower() != base_host:
            continue
        if not href_norm.startswith(base_path):
            continue
        if not (href_norm.lower().endswith(".htm") or href_norm.lower().endswith(".pdf")):
            continue
        seen.add(href_norm)
        candidates.append({"url": href, "text": link.get("text", "")})

    def _rank(c: dict[str, str]) -> tuple[int, ...]:
        text_lower = c.get("text", "").lower()
        for i, kw in enumerate(priority_keywords):
            if kw in text_lower:
                return (i,)
        return (len(priority_keywords),)

    candidates.sort(key=_rank)
    return candidates


async def handle_sec(
    client: httpx.AsyncClient,
    html_content: str,
    url: str,
) -> tuple[Optional[str], bool, str]:
    """Follow EX-99.1 exhibits; fall back to wrapper text."""
    exhibit_urls = extract_sec_exhibit_urls(html_content, url)
    if not exhibit_urls and "yahoofinance" in url.lower():
        exhibit_urls = [c["url"] for c in extract_yahoo_finance_exhibit_urls(html_content, url)]

    headers = sec_headers()
    for exhibit_url in exhibit_urls[:5]:
        try:
            resp = await client.get(
                exhibit_url,
                headers=headers,
                timeout=settings.doc_fetch_timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "pdf" in ctype or exhibit_url.lower().endswith(".pdf"):
                text = pdf_parser.pdf_to_text(resp.content, exhibit_url)
                if text and len(text) > 500:
                    return text, True, exhibit_url
            else:
                text = extract_sec_html_content(resp.text)
                if text and len(text) > 500:
                    return text, False, exhibit_url
        except Exception as exc:
            logger.debug("SEC exhibit fetch failed %s: %s", exhibit_url[:80], exc)
            continue

    text = extract_sec_html_content(html_content)
    if text and len(text) > 500:
        return text, False, url

    embedded = extract_exhibit_from_wrapper(html_content)
    if embedded and len(html_to_text(embedded)) > 500:
        return html_to_text(embedded), False, url

    return None, False, url


def wrapper_needs_exhibits(url: str) -> bool:
    return looks_like_html_url(url) or "sec.gov" in (url or "").lower()
