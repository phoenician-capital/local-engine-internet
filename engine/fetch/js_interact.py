"""JS IR interaction constants + async Playwright helpers.

Constants are ported from Earnings_tracker/tracker/summary/constants.py.
The interaction routine is a focused async port of fetch.py's expander/tab/
spinner/dynamic-link harvest — matched by label, never by company.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

from .urlutil import absolutize_html_links, is_pdf_url

logger = logging.getLogger("engine.fetch.js_interact")

JS_EXPANDER_LABEL_PATTERNS = [
    r"load\s*more",
    r"show\s*more",
    r"view\s*more",
    r"see\s*more",
    r"view\s*all",
    r"show\s*all",
    r"see\s*all",
    r"more\s*results",
    r"^more$",
    r"read\s*more",
    r"expand",
    r"older",
    r"archive",
    r"もっと見る",
    r"もっと",
    r"一覧",
    r"すべて",
    r"さらに",
    r"さらに表示",
    r"過去",
    r"もっと読む",
]

JS_TAB_SELECTORS = [
    "[role='tab']",
    "[aria-expanded='false']",
    "[aria-selected='false']",
    "ul.nav-tabs > li > a",
    "ul.tabs > li > a",
    ".tab-list [role='tab']",
    ".tab, .tabs a, .c-tab__item, .p-tab__item",
    "[data-tab], [data-toggle='tab'], [data-bs-toggle='tab']",
    ".accordion__title, .accordion-header, .accordion-toggle, .js-accordion",
]

JS_RESULTS_TAB_LABELS = [
    r"financial\s*results",
    r"periodic\s*reports?",
    r"current\s*reports?",
    r"quarterly",
    r"half[-\s]?year",
    r"interim",
    r"annual\s*report",
    r"presentations?",
    r"results?\s*(&|and)?\s*reports?",
    r"reports?",
    r"financial\s*(information|statements?)",
    r"earnings",
    r"raporty\s*okresowe",
    r"raporty\s*bie[żz]",
    r"raporty",
    r"決算",
    r"四半期",
    r"有価証券報告書",
    r"決算短信",
    r"適時開示",
    r"IR資料",
    r"財務",
    r"報告書",
]

JS_DATA_URL_ATTRS = (
    "data-url",
    "data-href",
    "data-pdf",
    "data-file",
    "data-src",
    "data-download",
    "data-document",
    "data-link",
    "data-target-url",
    "data-attachment",
    "data-doc",
)

JS_DOC_HOST_HINTS = (
    "xj-storage.jp",
    "/xcontents/",
    "irpocket",
    "q4cdn",
    "mziq",
    "cloudfront",
    "/documents/",
    "/attachment",
    "filedownload",
)

JS_LOADING_SPINNER_SELECTORS = (
    ".loading",
    ".spinner",
    ".loader",
    ".is-loading",
    ".c-loading",
    "[class*='loading']",
    "[class*='spinner']",
    "[class*='loader']",
    "[aria-busy='true']",
)

AGE_GATE_LABEL_PATTERNS = [
    r"i\s*am\s*(over\s*)?21\+?",
    r"^21\+?$",
    r"i\s*am\s*(over\s*)?18\+?",
    r"^18\+?$",
    r"i\s*am\s*of\s*legal\s*age",
    r"yes,?\s*i\s*am(\s*of\s*age)?",
    r"^yes$",
    r"^enter(\s*site)?$",
    r"^verify(\s*age)?$",
    r"^confirm$",
    r"^i\s*agree$",
    r"^agree$",
    r"^continue$",
]

_HARVEST_JS = """
(attrs) => {
  const out = new Set();
  const push = (v) => {
    if (!v || typeof v !== 'string') return;
    v.split(/[\\s,]+/).forEach(x => {
      if (x && (x.startsWith('http') || x.startsWith('/'))) out.add(x);
    });
  };
  document.querySelectorAll('a[href]').forEach(a => push(a.getAttribute('href')));
  document.querySelectorAll('*').forEach(el => {
    for (const name of attrs) { const val = el.getAttribute(name); if (val) push(val); }
    for (const attr of el.attributes) {
      if (attr.name.indexOf('data-') === 0 && /https?:|\\.pdf/i.test(attr.value)) push(attr.value);
    }
    const oc = el.getAttribute('onclick');
    if (oc) { const m = oc.match(/https?:[^'"\\s)]+/g); if (m) m.forEach(push); }
  });
  return Array.from(out);
}
"""


async def wait_for_spinners_gone(page: Any, timeout_ms: int = 1500) -> None:
    selector = ", ".join(JS_LOADING_SPINNER_SELECTORS)
    try:
        await page.wait_for_selector(selector, state="hidden", timeout=timeout_ms)
    except Exception:
        pass


async def _click_matching(page: Any, locator: Any, snap: Callable, limit: int = 3) -> int:
    clicks = 0
    try:
        count = min(await locator.count(), limit)
    except Exception:
        return 0
    for i in range(count):
        try:
            element = locator.nth(i)
            if not await element.is_visible():
                continue
            await element.click(timeout=1500)
            clicks += 1
            await asyncio.sleep(0.4)
            await snap()
        except Exception:
            continue
    return clicks


async def interact_page(page: Any, url: str) -> str:
    """Drive expanders/tabs and return concatenated HTML snapshots."""
    snapshots: list[str] = []
    seen: set[int] = set()

    def _append(html: str) -> None:
        if not html:
            return
        key = hash(html)
        if key not in seen:
            seen.add(key)
            snapshots.append(html)

    async def _capture_frames() -> str:
        parts = []
        try:
            frames = [f for f in page.frames if f != page.main_frame]
        except Exception:
            frames = []
        for frame in frames:
            try:
                frame_url = frame.url
                if not frame_url or frame_url.startswith(("about:", "data:")):
                    continue
                frame_html = await frame.content()
                if not frame_html or len(frame_html) < 200:
                    continue
                parts.append(absolutize_html_links(frame_html, frame_url))
            except Exception:
                continue
        return "\n<!-- iframe-snapshot -->\n".join(parts) if parts else ""

    async def snap() -> None:
        try:
            html = await page.content()
            frames_html = await _capture_frames()
            if frames_html:
                html = f"{html}\n{frames_html}"
            _append(html)
        except Exception:
            return

    try:
        await page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass
    await wait_for_spinners_gone(page)

    fragment = (urlparse(url).fragment or "").strip()
    if fragment:
        try:
            await page.evaluate(
                "(f) => { const el = document.getElementById(f) || "
                "document.querySelector(`[name='${f}']`); if (el) el.scrollIntoView(); }",
                fragment,
            )
            await asyncio.sleep(0.4)
        except Exception:
            pass

    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.4)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    await snap()

    clicks = 0
    for pattern in JS_EXPANDER_LABEL_PATTERNS:
        if clicks >= 8:
            break
        name_re = re.compile(pattern, re.IGNORECASE)
        for role in ("button", "link"):
            try:
                locator = page.get_by_role(role, name=name_re)
                clicks += await _click_matching(page, locator, snap, limit=2)
            except Exception:
                continue

    tab_clicks = 0
    for selector in JS_TAB_SELECTORS:
        if tab_clicks >= 12:
            break
        try:
            tab_clicks += await _click_matching(page, page.locator(selector), snap, limit=4)
        except Exception:
            continue
    for pattern in JS_RESULTS_TAB_LABELS:
        if tab_clicks >= 16:
            break
        name_re = re.compile(pattern, re.IGNORECASE)
        for role in ("tab", "button", "link"):
            try:
                locator = page.get_by_role(role, name=name_re)
                tab_clicks += await _click_matching(page, locator, snap, limit=2)
            except Exception:
                continue

    try:
        raw = await page.evaluate(_HARVEST_JS, list(JS_DATA_URL_ATTRS))
        candidates: set[str] = set()
        for candidate in raw or []:
            try:
                absolute = urljoin(url, candidate)
            except Exception:
                continue
            lowered = absolute.lower()
            if is_pdf_url(absolute) or any(hint in lowered for hint in JS_DOC_HOST_HINTS):
                candidates.add(absolute)
        if candidates:
            anchors = "".join(
                f'<a href="{c.replace(chr(34), "%22")}">dynamic-link</a>'
                for c in sorted(candidates)
            )
            _append(f"<html><body><!-- harvested-dynamic-links -->{anchors}</body></html>")
    except Exception as exc:
        logger.debug("dynamic-link harvest failed: %s", exc)

    await snap()
    if snapshots:
        return "\n<!-- interaction-snapshot -->\n".join(snapshots)
    try:
        html = await page.content()
        frames_html = await _capture_frames()
        return f"{html}\n{frames_html}" if frames_html else html
    except Exception:
        return ""


async def dismiss_age_gate(page: Any, url: str) -> None:
    for pattern in AGE_GATE_LABEL_PATTERNS:
        name_re = re.compile(pattern, re.IGNORECASE)
        for role in ("button", "link"):
            try:
                locator = page.get_by_role(role, name=name_re)
                if await locator.count() == 0:
                    continue
                await locator.first.click(timeout=2000)
                logger.info("clicked age-gate %s on %s", role, url[:80])
                await asyncio.sleep(1.0)
                return
            except Exception:
                continue
