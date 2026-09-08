"""Fetch ladder: httpx → curl_cffi → Playwright → PDF/SEC.

Ported from Earnings_tracker/tracker/summary/fetch.py, async-first so the
engine can run it inside FastAPI. FETCH_MODE gates optional tiers.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..config import DomainMode, FetchMode, parse_domain_mode, parse_fetch_mode, settings
from ..metrics import FETCH_TOTAL
from .cache import FetchCache
from .extract import extract_html, html_to_text
from .js_interact import dismiss_age_gate, interact_page
from .pdf import pdf_parser
from .policy import (
    AGE_VERIFICATION_COOKIES,
    BOT_BLOCK_STATUSES,
    DEFAULT_HEADERS,
    USER_AGENT,
    host_denied,
    is_bot_challenge,
    is_ir_url,
    is_sec_wrapper_url,
    should_skip_fetch,
)
from .sec import handle_sec, sec_headers
from .urlutil import is_pdf_url

logger = logging.getLogger("engine.fetch.ladder")

try:
    from curl_cffi.requests import AsyncSession as _CffiAsyncSession

    CURL_CFFI_AVAILABLE = True
except ImportError:
    _CffiAsyncSession = None  # type: ignore[assignment]
    CURL_CFFI_AVAILABLE = False

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    async_playwright = None  # type: ignore[assignment]
    PLAYWRIGHT_AVAILABLE = False

_CFFI_IMPERSONATE = "chrome"

_PROCESS_CACHE = FetchCache()


@dataclass
class Page:
    url: str
    final_url: str
    title: str
    text: str
    content_type: str
    is_pdf: bool
    tier: str
    ok: bool
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def looks_like_pdf(content_type: str, body: bytes, url: str) -> bool:
    if body and body[:5].startswith(b"%PDF"):
        return True
    if "pdf" in (content_type or "").lower():
        return not (
            body[:15].lstrip().lower().startswith(b"<!doctype")
            or body[:6].lstrip().lower().startswith(b"<html")
        )
    return is_pdf_url(url) and bool(body) and body[:5].startswith(b"%PDF")


def pdf_request_headers(url: str, referer: Optional[str] = None) -> dict[str, str]:
    parsed = urlparse(url)
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    headers = dict(DEFAULT_HEADERS)
    headers.update(
        {
            "Accept": "application/pdf,application/octet-stream,text/html;q=0.9,*/*;q=0.8",
            "Referer": referer or f"{origin}/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin" if referer else "none",
            "Sec-Fetch-User": "?1",
        }
    )
    return headers


def _failed(url: str, error: str, tier: str = "httpx") -> Page:
    FETCH_TOTAL.labels(tier=tier, status="error").inc()
    return Page(
        url=url,
        final_url=url,
        title="",
        text="",
        content_type="",
        is_pdf=False,
        tier=tier,
        ok=False,
        error=error,
    )


def _ok_page(
    url: str,
    final_url: str,
    title: str,
    text: str,
    content_type: str,
    is_pdf: bool,
    tier: str,
) -> Page:
    FETCH_TOTAL.labels(tier=tier, status="ok").inc()
    return Page(
        url=url,
        final_url=final_url,
        title=title,
        text=text,
        content_type=content_type,
        is_pdf=is_pdf,
        tier=tier,
        ok=True,
    )


def _with_age_cookies(headers: dict[str, str]) -> dict[str, str]:
    out = dict(headers)
    cookie = "; ".join(f"{k}={v}" for k, v in AGE_VERIFICATION_COOKIES.items())
    existing = out.get("Cookie") or out.get("cookie")
    out["Cookie"] = f"{existing}; {cookie}" if existing else cookie
    return out


async def _httpx_get(
    client: httpx.AsyncClient,
    url: str,
    headers: Optional[dict[str, str]] = None,
) -> httpx.Response:
    return await client.get(
        url,
        headers=_with_age_cookies(headers or DEFAULT_HEADERS),
        timeout=settings.doc_fetch_timeout,
        follow_redirects=True,
    )


async def curl_cffi_fetch(url: str, referer: Optional[str] = None) -> Optional[tuple[int, str, bytes, str]]:
    """Tier 2. Returns (status, content_type, body, final_url) or None."""
    if not CURL_CFFI_AVAILABLE or _CffiAsyncSession is None:
        return None
    parsed = urlparse(url)
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    try:
        async with _CffiAsyncSession() as session:
            resp = await session.get(
                url,
                headers={"Referer": referer or f"{origin}/"},
                impersonate=_CFFI_IMPERSONATE,
                timeout=30,
                allow_redirects=True,
            )
            ctype = resp.headers.get("content-type") or resp.headers.get("Content-Type") or ""
            final = str(getattr(resp, "url", url) or url)
            return int(resp.status_code), ctype, resp.content, final
    except Exception as exc:
        logger.debug("curl_cffi fetch failed for %s: %s", url[:80], exc)
        return None


async def playwright_fetch(url: str, referer: Optional[str] = None) -> Optional[tuple[str, str, bytes, str]]:
    """Tier 3. Returns (content_type, text_or_empty, body, final_url) or None.

    For HTML: body is the rendered HTML encoded as utf-8. For PDFs: raw bytes.
    """
    if not PLAYWRIGHT_AVAILABLE or async_playwright is None:
        return None
    parsed = urlparse(url)
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                )
                try:
                    await context.add_cookies(
                        [
                            {"name": name, "value": value, "url": url}
                            for name, value in AGE_VERIFICATION_COOKIES.items()
                        ]
                    )
                except Exception:
                    pass
                page = await context.new_page()
                try:
                    await page.goto(
                        url,
                        timeout=settings.headless_render_timeout_ms,
                        wait_until="domcontentloaded",
                    )
                except Exception:
                    try:
                        await page.goto(
                            referer or f"{origin}/",
                            timeout=settings.headless_render_timeout_ms,
                            wait_until="domcontentloaded",
                        )
                    except Exception:
                        pass
                await dismiss_age_gate(page, url)
                html = await interact_page(page, url)
                final = page.url or url
                if not html:
                    try:
                        html = await page.content()
                    except Exception:
                        html = ""
                return "text/html", html, html.encode("utf-8", errors="ignore"), final
            finally:
                await browser.close()
    except Exception as exc:
        logger.warning("Playwright render failed for %s: %s", url[:80], exc)
        return None


async def playwright_pdf(url: str, referer: Optional[str] = None) -> Optional[bytes]:
    if not PLAYWRIGHT_AVAILABLE or async_playwright is None:
        return None
    parsed = urlparse(url)
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=USER_AGENT, accept_downloads=True)
                page = await context.new_page()
                try:
                    await page.goto(
                        referer or f"{origin}/",
                        timeout=settings.headless_render_timeout_ms,
                        wait_until="domcontentloaded",
                    )
                except Exception:
                    pass
                resp = await context.request.get(url, headers={"Accept": "application/pdf,*/*"})
                if resp.ok:
                    body = await resp.body()
                    if looks_like_pdf(resp.headers.get("content-type", ""), body, url):
                        return body
            finally:
                await browser.close()
    except Exception as exc:
        logger.debug("Playwright PDF bypass failed for %s: %s", url[:80], exc)
    return None


def _cap_text(text: str, is_pdf: bool, max_chars: Optional[int]) -> str:
    if max_chars is not None:
        cap = max_chars
    else:
        cap = settings.max_chars_per_pdf if is_pdf else settings.max_chars_per_doc
    if cap and len(text) > cap:
        return text[:cap].rstrip()
    return text


def _page_from_bytes(
    url: str,
    final_url: str,
    body: bytes,
    content_type: str,
    tier: str,
    max_chars: Optional[int],
) -> Page:
    if looks_like_pdf(content_type, body, url):
        text = pdf_parser.pdf_to_text(body, final_url) or ""
        text = _cap_text(text, True, max_chars)
        title = final_url.rsplit("/", 1)[-1]
        return _ok_page(url, final_url, title, text, content_type or "application/pdf", True, tier)

    html = body.decode("utf-8", errors="ignore")
    cap = max_chars if max_chars is not None else settings.max_chars_per_doc
    text, title, canonical = extract_html(html, url=final_url, max_chars=cap)
    return _ok_page(
        url,
        canonical or final_url,
        title,
        text,
        content_type or "text/html",
        False,
        tier,
    )


async def fetch_url(
    client: httpx.AsyncClient,
    url: str,
    max_chars: Optional[int] = None,
    fetch_mode: Optional[str | FetchMode] = None,
    domain_mode: str | DomainMode = DomainMode.GENERAL_RESEARCH,
    cache: Optional[FetchCache] = None,
) -> Page:
    mode = fetch_mode if isinstance(fetch_mode, FetchMode) else parse_fetch_mode(
        fetch_mode or settings.fetch_mode
    )
    dmode = domain_mode if isinstance(domain_mode, DomainMode) else parse_domain_mode(str(domain_mode))
    store = cache if cache is not None else _PROCESS_CACHE

    if not url:
        return _failed(url, "empty url")
    if should_skip_fetch(url):
        return _failed(url, "blocked social domain")
    denied, reason = host_denied(url, dmode)
    if denied:
        return _failed(url, reason)

    cached = store.get(url)
    if isinstance(cached, Page):
        FETCH_TOTAL.labels(tier="cache", status="ok" if cached.ok else "error").inc()
        return cached

    try:
        page = await _fetch_uncached(client, url, max_chars, mode)
    except Exception as exc:
        page = _failed(url, f"{type(exc).__name__}: {exc}")
    store.set(url, page, ok=page.ok)
    return page


async def _fetch_uncached(
    client: httpx.AsyncClient,
    url: str,
    max_chars: Optional[int],
    mode: FetchMode,
) -> Page:
    headers = sec_headers() if "sec.gov" in url.lower() else dict(DEFAULT_HEADERS)
    want_pdf = is_pdf_url(url)

    # --- Direct PDF: escalate past WAF ---
    if want_pdf and "sec.gov" not in url.lower():
        pdf_page = await _download_pdf_resilient(client, url, mode, max_chars)
        if pdf_page:
            return pdf_page

    # --- IR pages: prefer Playwright when FULL ---
    if is_ir_url(url) and not want_pdf and mode is FetchMode.FULL:
        rendered = await playwright_fetch(url)
        if rendered:
            _ctype, html, body, final = rendered
            if html and len(html_to_text(html)) >= settings.thin_html_char_threshold:
                return _page_from_bytes(url, final, body, "text/html", "playwright", max_chars)

    # --- Tier 1: httpx ---
    status = 0
    body = b""
    ctype = ""
    final_url = url
    blocked = False
    try:
        resp = await _httpx_get(client, url, headers=headers if "sec.gov" in url.lower() else pdf_request_headers(url) if want_pdf else DEFAULT_HEADERS)
        status = resp.status_code
        body = resp.content
        ctype = resp.headers.get("Content-Type") or ""
        final_url = str(resp.url)
        if status in BOT_BLOCK_STATUSES or (body and is_bot_challenge(body.decode("utf-8", errors="ignore"))):
            blocked = True
        elif status >= 400:
            # Non-WAF error: still try lower tiers only if it looks like a block.
            return _failed(url, f"HTTP {status}", tier="httpx")
    except httpx.HTTPError as exc:
        logger.info("httpx error for %s (%s); attempting bypass", url[:80], type(exc).__name__)
        blocked = True

    if not blocked and body:
        if is_sec_wrapper_url(url) and ("htm" in url.lower() or "html" in ctype.lower()):
            text, is_pdf, resolved = await handle_sec(client, body.decode("utf-8", errors="ignore"), str(final_url))
            if text:
                text = _cap_text(text, is_pdf, max_chars)
                return _ok_page(url, resolved, resolved.rsplit("/", 1)[-1], text, ctype, is_pdf, "sec")
        page = _page_from_bytes(url, final_url, body, ctype, "httpx", max_chars)
        thin = (not page.is_pdf) and len(page.text) < settings.thin_html_char_threshold
        if not thin:
            return page
        # Thin HTML — escalate to Playwright when allowed.
        if mode is FetchMode.FULL:
            rendered = await playwright_fetch(url)
            if rendered:
                _c, html, rbody, final = rendered
                if html and len(html_to_text(html)) > len(page.text):
                    return _page_from_bytes(url, final, rbody, "text/html", "playwright", max_chars)
        return page

    # --- Tier 2: curl_cffi ---
    if mode is not FetchMode.HTTPX_ONLY:
        cffi = await curl_cffi_fetch(url)
        if cffi:
            st, c_ctype, c_body, c_final = cffi
            if st == 200 and c_body:
                return _page_from_bytes(url, c_final, c_body, c_ctype, "curl_cffi", max_chars)

    # --- Tier 3: Playwright ---
    if mode is FetchMode.FULL:
        if want_pdf:
            pdf_bytes = await playwright_pdf(url)
            if pdf_bytes:
                text = pdf_parser.pdf_to_text(pdf_bytes, url) or ""
                return _ok_page(
                    url, url, url.rsplit("/", 1)[-1],
                    _cap_text(text, True, max_chars),
                    "application/pdf", True, "playwright",
                )
        rendered = await playwright_fetch(url)
        if rendered:
            _c, html, rbody, final = rendered
            if rbody:
                return _page_from_bytes(url, final, rbody, "text/html", "playwright", max_chars)

    return _failed(url, f"all fetch tiers failed (last_status={status})", tier="httpx")


async def _download_pdf_resilient(
    client: httpx.AsyncClient,
    url: str,
    mode: FetchMode,
    max_chars: Optional[int],
) -> Optional[Page]:
    headers = pdf_request_headers(url)
    try:
        resp = await _httpx_get(client, url, headers=headers)
        if resp.status_code == 200 and looks_like_pdf(
            resp.headers.get("Content-Type", ""), resp.content, url
        ):
            return _page_from_bytes(url, str(resp.url), resp.content, resp.headers.get("Content-Type", ""), "httpx", max_chars)
        if resp.status_code not in BOT_BLOCK_STATUSES:
            return None
        logger.info("PDF fetch blocked (HTTP %s) for %s", resp.status_code, url[:80])
    except httpx.HTTPError:
        logger.info("PDF fetch errored for %s; attempting bypass", url[:80])

    if mode is not FetchMode.HTTPX_ONLY:
        cffi = await curl_cffi_fetch(url)
        if cffi:
            st, ctype, body, final = cffi
            if st == 200 and looks_like_pdf(ctype, body, url):
                return _page_from_bytes(url, final, body, ctype, "curl_cffi", max_chars)

    if mode is FetchMode.FULL:
        pdf_bytes = await playwright_pdf(url)
        if pdf_bytes:
            return _page_from_bytes(url, url, pdf_bytes, "application/pdf", "playwright", max_chars)
    return None
