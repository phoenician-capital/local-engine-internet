# Surgical pass — fields and fetch logic the bible originally missed

Read against live code 2026-09-08. If `engine-bible.md` and this file disagree, **this file wins** on fetch/SERP details.

---

## 1. SerpAPI response is richer than `{title, snippet, link}`

Portfolio EP `smart_finder.py` (and Earnings finders) already consume:

| Field | Use |
|---|---|
| `organic_results[].title` | hit title |
| `organic_results[].snippet` | hit snippet |
| `organic_results[].link` | URL |
| `organic_results[].position` | rank |
| `answer_box.answer` or `.snippet` + `.link` | tagged `is_answer_box` |
| `knowledge_graph.title/description/attributes[]/link` | tagged `is_knowledge_graph` |
| `related_questions[]` (first **2**) | `question` + `snippet` + `link` |

Dedup: snippet[:120] **or** url. Site-restricted queries that return nothing **do not** count against query budget. Sleep **0.4s** between queries.

A drop-in `/v1/search` must be able to return these extra hit types or EP calendar quality drops.

Router today **throws away** answer_box / KG / related. Do not copy that.

---

## 2. The company already has a fetch engine — copy it, don’t invent

**Canonical implementation:** `Earnings_tracker/tracker/summary/fetch.py` (+ `html_cleaner.py`, `pdf_parser.py`, `sec_handler.py`, `fetch_cache.py`).

Ported cousin: `phoenician-portfolio/.../calendar/ir_crawl.py`.

### Fetch ladder (in order)

1. **httpx/requests** with Chrome-like headers (`Accept-Language`, `Sec-Fetch-*`, gzip/br)
2. If HTTP in `{401,403,406,409,429,503}` → **curl_cffi** impersonate `"chrome"` (TLS/JA3). Soft dep.
3. If still thin/blocked → **Playwright Chromium** headless
4. PDF: browser-like headers + **Referer** (same-origin site root) or WAF 403s the file

### Limits (Earnings `summary/constants.py`)

| Constant | Value |
|---|---|
| `DOC_FETCH_TIMEOUT` | 20s |
| `MAX_CHARS_PER_DOC` | 8_000 |
| `MAX_CHARS_PER_PDF` | 25_000 |
| `MAX_TOTAL_DOC_CHARS` | 50_000 |
| `MAX_PDF_BYTES` | 25 MB |
| `THIN_HTML_CHAR_THRESHOLD` | 400 (Earnings fetch) / 800 (EP IR crawl) |
| `HEADLESS_RENDER_TIMEOUT_MS` | 15_000 (Earnings) / 45_000 (EP IR) |
| `MAX_DOCS_TO_FETCH` | 3 ranked candidates |
| Age-gate cookies | `age_verified=true`, `over18=true`, `legal_age=true`, `is_over_18=true` |

EP IR crawl: max text 80_000 chars; wait 2.5s after `domcontentloaded` for JS calendar rows; max 2 calendar subpages; skip mailto/js/tel/#/cookie/privacy/social.

### HTML → text (already written)

`html_to_text`: strip script/style/svg/head; br/p/div/li/tr/h* → newline; unescape nbsp/amp/lt/gt/quot/euro/pound; drop Cookie/Privacy/Accept Cookies chrome.

### JS IR interaction (Earnings) — required for APAC/EU issuers

Click by **label**, never by company:

- Expanders: load/show/view more, もっと見る, 一覧, すべて, さらに表示, 過去
- Tabs: `[role=tab]`, Bootstrap/ARIA accordions
- Results tab labels: financial results, 決算, 四半期, 有価証券報告書, 決算短信, 適時開示, raporty okresowe
- Hidden PDF attrs: `data-url`, `data-pdf`, `data-file`, …
- Doc hosts without `.pdf`: `xj-storage.jp`, `irpocket`, `q4cdn`, `mziq`, cloudfront `/documents/`
- Wait for spinners to disappear: `.loading`, `[aria-busy=true]`, …

### SEC EDGAR

Required User-Agent or you get 429:

- Earnings: `Mozilla/5.0 (compatible; EarningsTracker/1.0; +https://phoeniciancapital.com)`
- Screening: `settings.ingestion.sec_edgar_user_agent`
- Portfolio insiders: `SEC_EDGAR_USER_AGENT` (must include contact email)

`SECHandler` follows wrapper pages → EX-99.1 exhibits. Optional LLM help if exhibits not found. This is **fetch**, not Google search — keep a dedicated SEC path.

---

## 3. Prompt budgets the engine must respect

PI `config/config.py` (chars, not tokens):

| Budget | Default | Meaning |
|---|---|---|
| `WEB_CONTEXT_BUDGET_CHARS` | **150_000** | Per-section web inject |
| `RAG_CONTEXT_MAX_CHARS` | 800_000 | File RAG (not this engine) |
| `FINANCIALS_BUDGET_CHARS` | 400_000 | CapIQ Excel |
| `PREVIOUS_PARTS_BUDGET_CHARS` | 300_000 | Prior sections |

DeepSeek web has a **prompt hard limit** (`_WEB_PROMPT_HARD_LIMIT`) — do not dump raw pages untrimmed. Composite `/v1/research` should cap per page (Earnings uses 8k HTML / 25k PDF).

CJK: Japanese/Chinese ≈ 1 char/token. Leave headroom.

---

## 4. Domain allow/deny lists (do not invent new ones)

### Never treat as the company’s own site (PI `prefetch_pipeline.py` `AGGREGATOR_DOMAINS`)

wikipedia, linkedin, bloomberg, reuters, yahoo, google, facebook, instagram, twitter/x, youtube, marketscreener, investing, ft, wsj, stockanalysis, tradingview, morningstar, marketwatch, cnbc, simplywall.st, annualreports, crunchbase, zoominfo, dnb, globenewswire, prnewswire, businesswire, seekingalpha, fool, barrons, forbes, wallmine, tipranks, finance.yahoo, msn.

Google CSE: `customsearch.googleapis.com/customsearch/v1?key=&cx=&q=&num=5` timeout 20s. Query: `"{name} official website investor relations"`. Return first non-aggregator **host**.

### Never as IR/PDF source (PI `company_pdf_downloads/perplexity.py`)

yahoo, bloomberg, **sec.gov / edgar.sec.gov**, nasdaq, nyse, asx.com.au, marketwatch, annualreports, morningstar, reuters, investing, fool, seekingalpha.

Note: Earnings **does** fetch SEC. PDF-crawler blocklist ≠ Earnings. Make deny lists **per-mode** (`ir_discovery` vs `earnings_doc` vs `general_research`).

### RFW / reviews

Trustpilot/Reddit: SerpAPI finds URL, then scrape. WAF markers in `serpapi_helper.BOT_CHALLENGE_MARKERS`: “please verify you are a human”, Cloudflare, Sucuri, Distil “pardon the interruption”, “are you a robot”, “403 forbidden”. Check first 5 kB.

Trustpilot score floors: 25 without domain hint, **50** with expected domain (blocks “X alternatives” SERP traps).

---

## 5. Perplexity prefetch output is two citation blocks

`web_search.py` appends:

1. `result["citations"]` → `[SOURCE: Web Citation N]` + `[PUBLIC_URL: url]`
2. `result["search_results"]` → `[SOURCE: {title} (Date: {date})]` + `[PUBLIC_URL: url]`

A replacement must emit **both** shapes or section writers lose hyperlinks. Raises `RuntimeError` on failure (not an empty success dict).

---

## 6. Confidence scoring after fetch (Earnings)

Do not delete this when swapping search:

| Situation | Delta |
|---|---|
| Official IR PDF | +0.30 |
| Any PDF | +0.15 |
| Official page, no PDF | 0 |
| Non-official non-PDF | −0.20 |
| Snippet-only, no docs | −0.30 |

---

## 7. Google CSE was under-specified

```
GET https://www.googleapis.com/customsearch/v1
  key=GOOGLE_API_KEY
  cx=GOOGLE_SEARCH_ENGINE_ID
  q=...
  num=5
```

Items: `{link, title, snippet}`. Used only for official website. Same `GOOGLE_API_KEY` also unlocks Gemini — do not confuse the two products.

---

## 8. Insider / regulator HTML fetch (portfolio)

Not “search,” but a second fetch corpus: EDGAR, RNS, BaFin, ASX 3Y (pypdf), SGX, SEDI, NSE, Nordic, KIND, FI, ESPI, Borsa, ATHEX, BVB… User-Agent `phoenician-portfolio-insiders/1.0`. Out of v1 scope unless we advertise a generic fetch.

---

## 9. n8n

PI chatbot primary path in the frontend is an **n8n webhook** `chatbot-action` plus Python `/chatbot/*`. Search quality for chat still lands in Python (`call_claude_web_chatbot`). Wiring the engine there covers the UI.

---

## 10. What “perfect” means after this pass

v1 is not “SerpAPI snippets + Tavily.” Perfect means:

1. SERP with organic + answer_box + KG + related_questions
2. Fetch ladder: HTTP → curl_cffi → Playwright
3. PDF + HTML extract with the Earnings caps
4. JS tab/expander labels (EN/JP/PL)
5. SEC exhibit path with a real User-Agent
6. Per-mode domain deny lists
7. `[PUBLIC_URL]` citation blocks
8. `WEB_CONTEXT_BUDGET_CHARS` trim
9. Fail closed on research; never “answer from knowledge”
10. Same `web_search` tool schema so Flash can call it

The fetch ladder already exists in Earnings. **Port it into this repo** rather than rewriting it.
