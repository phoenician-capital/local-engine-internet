"""Query hygiene ported from Earnings_tracker/tracker/summary/search.py."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

_LEGAL_SUFFIX_RE = re.compile(
    r"\s*(?:PLC|plc|Inc\.?|Inc|Limited|Ltd|Group|Corp\.?|Corporation|"
    r"S\.A\.|SA|ASA|ASA International)\s*",
)


def clean_company(company: str) -> str:
    """Strip legal suffixes so site:/quote queries stay tight."""
    if not company:
        return ""
    return _LEGAL_SUFFIX_RE.sub(" ", company).strip() or company


def host_from_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    host = urlparse(raw).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def site_query(domain: str, rest: str = "") -> str:
    host = host_from_url(domain)
    rest = (rest or "").strip()
    return f"site:{host} {rest}".strip() if host else rest


def filetype_pdf(query: str) -> str:
    q = (query or "").strip()
    if "filetype:pdf" in q.lower():
        return q
    return f"{q} filetype:pdf".strip()


def quarter_num(quarter: str) -> Optional[str]:
    if not quarter:
        return None
    m = re.search(r"[1-4]", quarter)
    return m.group(0) if m else None


def build_simple_queries(
    ticker: str,
    company: str,
    quarter: str,
    year: int,
    ir_domain: Optional[str] = None,
) -> list[str]:
    """Aggressive PDF-oriented queries — Earnings ``build_simple_queries``.

    Judgment stays with the caller (ranker / model). This only builds strings.
    """
    ticker_clean = ticker.split(".")[0].upper()
    company_clean = clean_company(company)
    qn = quarter_num(quarter)
    yy = str(year)[-2:]

    queries: list[str] = []
    if qn:
        queries.append(f'"{company_clean}" "{qn}Q{yy}" filetype:pdf')
        queries.append(f'"{company_clean}" "Q{qn}{yy}" filetype:pdf')
        queries.append(f'"{company_clean}" "Q{qn} {year}" filetype:pdf')
        queries.append(f'"{ticker_clean}" "{qn}Q{yy}" filetype:pdf')
        queries.append(f'"{ticker_clean}" "Q{qn}{yy}" filetype:pdf')

    queries.append(f'"{company_clean}" "{year}" results filetype:pdf')
    queries.append(f'"{company_clean}" earnings {year} filetype:pdf')
    queries.append(f'"{ticker_clean}" earnings {year} filetype:pdf')
    queries.append(f'"{company_clean}" earnings release {year} filetype:pdf')

    if ir_domain:
        domain = host_from_url(ir_domain)
        if domain:
            if qn:
                queries.append(f'site:{domain} "{qn}Q{yy}" filetype:pdf')
                queries.append(f'site:{domain} "Q{qn}{yy}" filetype:pdf')
                queries.append(f'site:{domain} "Q{qn} {year}" filetype:pdf')
            queries.append(f'site:{domain} "{year}" filetype:pdf')
            queries.append(f'site:{domain} "earnings" filetype:pdf {year}')
            queries.append(f'site:{domain} "results" filetype:pdf {year}')

    if qn:
        queries.append(f'"{company_clean}" "{qn}Q{yy}"')
        queries.append(f'"{company_clean}" "Q{qn}{yy}"')
        queries.append(f'"{ticker_clean}" "{qn}Q{yy}"')

    queries.append(f'"{company_clean}" {year} investor relations results')
    queries.append(f'"{ticker_clean}" {year} earnings results')

    if qn:
        queries.append(f'q4cdn.com "{company_clean}" "{qn}Q{yy}"')
        queries.append(f'q4cdn.com "{ticker_clean}" "{qn}Q{yy}"')
        queries.append(f'mziq.com "{company_clean}" "{qn}Q{yy}"')

    seen: set[str] = set()
    deduped = [q for q in queries if q and not (q in seen or seen.add(q))]
    return deduped[:15]


def serpapi_tbs_for_recency(recency_days: Optional[int]) -> Optional[str]:
    if not recency_days:
        return None
    if recency_days <= 1:
        return "qdr:d"
    if recency_days <= 7:
        return "qdr:w"
    if recency_days <= 31:
        return "qdr:m"
    return "qdr:y"


def brave_freshness(recency_days: Optional[int]) -> Optional[str]:
    if not recency_days:
        return None
    if recency_days <= 1:
        return "pd"
    if recency_days <= 7:
        return "pw"
    if recency_days <= 31:
        return "pm"
    return "py"
