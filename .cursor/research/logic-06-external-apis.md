# External search + data APIs (every key)

These are **not LLMs**. They are the internet/data pipes the models consume. Recorded 2026-09-08.

---

## 1. SerpAPI — Google search proxy

**Key:** `SERPAPI_KEY` (also accepted as `SERPAPI_API_KEY` when portfolio injects from `phoenician-ai-api-keys`).  
**Endpoint:** `GET https://serpapi.com/search` · `engine=google`  
**Python:** `from serpapi import GoogleSearch` or raw `requests`.

| Repo | File | What it finds |
|---|---|---|
| **Earnings_tracker** | `tracker/summary/search.py` | Targeted Google queries for earnings docs |
| | `tracker/summary/discovery.py` + `discovery_strategies.py` | PDF / IR page discovery |
| | `tracker/summary_finder.py` | Orchestrates SerpAPI → fetch → DeepSeek rank/extract |
| | `tracker/smart_finder.py` | Calendar events; 3 retries; `SerpApiAccountError` |
| | `tracker/webcast_finder.py` | Webcast / register URLs |
| | `tracker/news/serpapi_news.py` | News L1 keyword search + heuristic score |
| | `tracker/earnings/extract_earnings.py` | LLM extract **from** SerpAPI result pages |
| **phoenician-portfolio** | `earnings_predictor/calendar/smart_finder.py` | Next earnings date (SerpAPI then DeepSeek JSON) |
| | `earnings_bridge.py` | Injects `SERPAPI_KEY` from AWS secret |
| **phoenician-intelligence** | `Company_Review/scrapers/serpapi_helper.py` | Shared helper: Trustpilot/Reddit/company URL find |
| | `trustpilot_scraper_serp.py` | Trustpilot listing URL (scored, domain-aware) |
| | `reddit_scraper_serp.py` | Reddit threads |
| | `ir_email_lookup.py` | IR email from Google snippets + page crawl |
| | `engines/red_flag_workflow/rfw_serp.py` | Section 12 preflight: 2 Google queries (short seller / Substack), max 10 bullets, skip if no key |
| **ai-router** | `app/tools/web_search.py` | `phoenician_tools.web_search` — 5 organic results, title/snippet/link |

**Not used in:** screening-engine, capiq-screen-agent, Linker, investor-portal, dcf--app.

**Fail:** Earnings/portfolio raise `SerpApiAccountError` on quota/auth; PI reviews raise `SerpAPIKeyMissing`; RFW preflight skips silently; ai-router skips the provider.

---

## 2. Tavily — search API

**Key:** `TAVILY_API_KEY`  
**Endpoint:** `POST https://api.tavily.com/search`  
**Only repo:** `ai-router` (`app/tools/web_search.py`). Runs **in parallel with SerpAPI**. No other Phoenician product uses it.

---

## 3. Vendor-native web search (no SerpAPI)

These are LLM tools, not a separate search product — listed so they are not forgotten.

| Provider | Tool | Used by |
|---|---|---|
| Anthropic | `web_search_20250305` | PI writers/chat/PDF discovery, screening `complete_with_search`, CapIQ chat/screen/auditor, portfolio debate |
| Gemini | `GoogleSearch()` / `google_search` | PI `call_gemini_web`, CJA/competitors/beta, Earnings news L2, dcf--app |
| Perplexity | Sonar built-in search | PI prefetch/RFW/TAM/IPO/capacity, screening news+transcripts |
| DeepSeek cloud | `/responses` `web_search` | PI cheap `call_deepseek_writing_web` |
| Z.ai | `/paas/v4/web_search` | CapIQ GLM desk |
| OpenRouter | plugin `{id:'web'}` | CapIQ Llama desk |

---

## 4. Google Custom Search (not SerpAPI)

**Keys:** `GOOGLE_API_KEY` + `GOOGLE_SEARCH_ENGINE_ID`  
**Where:** PI `prefetch_pipeline.py` website lookup — cache → FMP → **Google CSE** → Claude web last resort.

Gemini `GOOGLE_API_KEY` is also used for Gemini models / Google Search grounding (same env name, different product).

---

## 5. Financial / document data (not search, but fed to LLMs)

| API | Key | Repos | Role |
|---|---|---|---|
| **FMP** (Financial Modeling Prep) | `FMP_KEY` / `FMP_API_KEY` | PI `fmp_client.py`, prefetch website; portfolio `universe.py` / `rates.py`; Factsheet `vite.portfolioApi.ts`; investor-portal `StrategyTop5Service` | Profiles, prices, treasuries. PI notes income-statement can 402. |
| **yfinance** | none | PI prices/charts; portfolio prices/live/OHLCV; screening market_data; Factsheet Yahoo `^SP500TR` | Quotes, history, FX. No search. |
| **CapIQ** | `CAPIQ_USERNAME` / `CAPIQ_PASSWORD` (+ pool `_N`) | PI Excel/filings/competitors; CapIQ screen agent; Linker | Source of truth financials. Selenium, not an LLM. |
| **AlphaSense** | `ALPHASENSE_USERNAME` / `ALPHASENSE_PASSWORD` | PI login + PDF RAG (`USE_ALPHASENSE_RETRIEVAL`, sections 5 & 11) | Analyst PDFs. `SKIP_ALPHASENSE` skip. |
| **Vertex AI Search** | GCP creds + datastore | PI RAG `phoenician-intelligence-rag-v3` | File RAG, not live web |
| **Gemini File Search** | `GEMINI_API_KEY` | PI RAG + chatbot PDF search | File RAG |
| **OpenAI embeddings** | `OPENAI_API_KEY` | screening-engine pgvector | RAG only |

---

## 6. Inventory by env var

| Env | Product | Who uses it |
|---|---|---|
| `SERPAPI_KEY` | SerpAPI Google | Earnings, PI reviews/IR/RFW, ai-router, portfolio EP calendar |
| `SERPAPI_API_KEY` | same | Portfolio inject alias |
| `TAVILY_API_KEY` | Tavily | ai-router only |
| `PERPLEXITY_API_KEY` | Sonar web | PI + screening-engine |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini + Search grounding | PI, Earnings news, dcf--app, screening Gemini complete |
| `GOOGLE_SEARCH_ENGINE_ID` | Google CSE | PI prefetch website only |
| `ZAI_API_KEY` | Z.ai web_search | CapIQ GLM |
| `OPENROUTER_API_KEY` | OpenRouter web plugin | CapIQ Llama |
| `FMP_KEY` / `FMP_API_KEY` | FMP | PI, portfolio, Factsheet, portal strategy |
| `CAPIQ_*` | S&P CapIQ | PI, screen, Linker |
| `ALPHASENSE_*` | AlphaSense | PI RAG |
| `phoenician-ai-api-keys` | AWS blob | OpenAI + DeepSeek + SerpAPI (+ FMP in some apps) |

---

## 7. What a local search layer must replace first

If the goal is “local LLM can search the internet”:

1. **SerpAPI** — heaviest real Google usage (Earnings whole pipeline, PI reviews/IR/RFW, router, EP calendar)
2. **Vendor tools** — Anthropic / Gemini / Perplexity / DeepSeek / Z.ai / OpenRouter web
3. **Tavily** — only router; easy to fold in
4. **Google CSE** — one PI prefetch path

Do **not** treat FMP, yfinance, CapIQ, AlphaSense, Vertex as “search.” They are data. The local engine should not pretend to replace CapIQ.
