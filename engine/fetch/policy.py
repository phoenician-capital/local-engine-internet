"""Per-mode deny lists and WAF / bot-challenge markers.

Lists are copied from PI prefetch_pipeline.py, company_pdf_downloads/perplexity.py,
and Company_Review/scrapers/serpapi_helper.py — do not invent new ones.
"""
from __future__ import annotations

from urllib.parse import urlparse

from ..config import DomainMode

# PI prefetch_pipeline.py AGGREGATOR_DOMAINS — never treat as the company's own site.
AGGREGATOR_DOMAINS: tuple[str, ...] = (
    "wikipedia.org",
    "linkedin.com",
    "bloomberg.com",
    "reuters.com",
    "yahoo.com",
    "google.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "marketscreener.com",
    "investing.com",
    "ft.com",
    "wsj.com",
    "stockanalysis.com",
    "tradingview.com",
    "morningstar.com",
    "marketwatch.com",
    "cnbc.com",
    "simplywall.st",
    "annualreports.com",
    "crunchbase.com",
    "zoominfo.com",
    "dnb.com",
    "globenewswire.com",
    "prnewswire.com",
    "businesswire.com",
    "seekingalpha.com",
    "fool.com",
    "barrons.com",
    "forbes.com",
    "wallmine.com",
    "tipranks.com",
    "finance.yahoo.com",
    "msn.com",
)

# PI company_pdf_downloads/perplexity.py — never as IR/PDF source. Includes SEC.
IR_DISCOVERY_BLOCKLIST: tuple[str, ...] = (
    "yahoo.com",
    "bloomberg.com",
    "sec.gov",
    "edgar.sec.gov",
    "nasdaq.com",
    "nyse.com",
    "asx.com.au",
    "marketwatch.com",
    "annualreports.com",
    "morningstar.com",
    "reuters.com",
    "investing.com",
    "fool.com",
    "seekingalpha.com",
)

# general_research: empty except spam/social (plan §6).
SOCIAL_SPAM_DOMAINS: tuple[str, ...] = (
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
)

# Earnings fetch.py skips these on every path.
ALWAYS_SKIP_FETCH: tuple[str, ...] = (
    "facebook.com",
    "twitter.com",
    "instagram.com",
)

# PI serpapi_helper.BOT_CHALLENGE_MARKERS — first 5 kB of the body.
BOT_CHALLENGE_MARKERS: tuple[str, ...] = (
    "please verify you are a human",
    "attention required! | cloudflare",
    "sucuri website firewall",
    "pardon the interruption",
    "are you a robot",
    "403 forbidden",
)

BOT_BLOCK_STATUSES = frozenset({401, 403, 406, 409, 429, 503})

AGE_VERIFICATION_COOKIES = {
    "age_verified": "true",
    "over18": "true",
    "legal_age": "true",
    "is_over_18": "true",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def supported_accept_encoding() -> str:
    """Only advertise encodings this process can actually decode.

    Chrome-like ``br`` without the brotli package leaves httpx holding
    compressed bytes, which then get treated as page text.
    """
    encodings = ["gzip", "deflate"]
    try:
        import brotli  # noqa: F401
        encodings.append("br")
    except ImportError:
        try:
            import brotlicffi  # noqa: F401
            encodings.append("br")
        except ImportError:
            pass
    return ", ".join(encodings)


DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": supported_accept_encoding(),
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def hostname(url: str) -> str:
    if not url:
        return ""
    raw = url if "://" in url else f"https://{url}"
    host = urlparse(raw).netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def deny_list_for(mode: DomainMode) -> tuple[str, ...]:
    if mode is DomainMode.IR_DISCOVERY:
        # Aggregators + IR PDF blocklist (SEC is blocked here; Earnings mode allows it).
        seen: set[str] = set()
        out: list[str] = []
        for d in (*IR_DISCOVERY_BLOCKLIST, *AGGREGATOR_DOMAINS, *SOCIAL_SPAM_DOMAINS):
            if d not in seen:
                seen.add(d)
                out.append(d)
        return tuple(out)
    if mode is DomainMode.EARNINGS_DOC:
        return SOCIAL_SPAM_DOMAINS
    return SOCIAL_SPAM_DOMAINS


def host_denied(url: str, mode: DomainMode) -> tuple[bool, str]:
    host = hostname(url)
    if not host:
        return False, ""
    for domain in deny_list_for(mode):
        if _host_matches(host, domain):
            return True, f"denied by {mode.value} list ({domain})"
    return False, ""


def should_skip_fetch(url: str) -> bool:
    host = hostname(url)
    return any(_host_matches(host, d) for d in ALWAYS_SKIP_FETCH)


def is_bot_challenge(html: str, max_bytes: int = 5000) -> bool:
    if not html:
        return False
    head = html[:max_bytes].lower()
    return any(m in head for m in BOT_CHALLENGE_MARKERS)


def is_ir_url(url: str) -> bool:
    lowered = (url or "").lower()
    return "ir." in lowered or "investor" in lowered


def is_sec_wrapper_url(url: str) -> bool:
    url_lower = (url or "").lower()
    if "sec.gov" in url_lower:
        return True
    if "cdn.yahoofinance.com" in url_lower and "sec-filings" in url_lower:
        return True
    return False
