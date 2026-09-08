# Engine bible — everything needed to build local-engine-internet

This is the build spec distilled from every `phoenician-capital` repo. Other `logic-*.md` files are the evidence. This file is what to implement against.

---

## 1. Job

Local DeepSeek Brains (`deepseek-v4-flash` on vLLM, behind `ai-router`) cannot search or fetch the web. Cloud models do that today via vendor tools and SerpAPI. This repo must give **every company app** a search+fetch layer that is better than snippets, so they can leave Claude/Gemini/Perplexity/DeepSeek-cloud web without losing research quality.

**Split:**

| Layer | Owner |
|---|---|
| Inference, load balance, auth | keep `ai-router` |
| Search, fetch, extract, cite | **this repo** |
| Prompts and workflows | stay in each product |

Do not become a second unused proxy. Either (A) ai-router delegates `web_search` here, or (B) this service is the search backend apps and the router both call.

---

## 2. Two capabilities every caller eventually needs

### A. `search(query) → hits`

Google-quality SERP: title, snippet/content, url, optional date, optional source label.

Already spoken:

- SerpAPI `organic_results[]` → `{title, snippet, link, position}` **plus** `answer_box`, `knowledge_graph`, `related_questions` (see `engine-surgical.md`)
- Tavily `results[]` → `{title, content, url}`
- Router string format: labeled blocks the model weighs itself

**Fetch already exists in-house.** Do not invent one. Port `Earnings_tracker/tracker/summary/fetch.py` (HTTP → curl_cffi Chrome JA3 → Playwright → PDF/SEC). Details: `engine-surgical.md`.

### B. `fetch(url) → page`

Nobody in the company has a shared fetch/extract service. Earnings fetches pages ad hoc after SerpAPI. PI scrapes Trustpilot/Reddit after SerpAPI finds the URL. Screening/CapIQ/PI writers never fetch — they rely on the vendor tool to “have read the web.”

A local Brain **cannot** do that. The engine must:

1. Search
2. Fetch the chosen URLs
3. Extract readable text (HTML → text; PDF → text)
4. Return labeled excerpts + canonical URLs for `[PUBLIC_URL:]` / citations

JS-heavy IR pages (webcasts, calendars) may need a headless fetch later. Start with HTTP + readability + PDF.

---

## 3. Insertion points (how apps will actually call this)

| Priority | App | Today | Hook to change |
|---|---|---|---|
| 1 | `ai-router` | SerpAPI∥Tavily snippets, `phoenician_tools: ["web_search"]` | Replace `run_web_search` body — **same tool schema** |
| 2 | PI cheap | `call_deepseek_writing_web` → DeepSeek cloud Responses `web_search` | Point DeepSeek client at router **and** inject `phoenician_tools`, **or** call this engine from the shim |
| 3 | PI prefetch | `fetch_company_web_data` → Perplexity `sonar-pro` + citations | Swap HTTP target; keep citation shape |
| 4 | Earnings | SerpAPI find + DeepSeek judge + fetch | Keep “search is dumb, LLM judges” — swap only the search backend |
| 5 | Screening | Anthropic `complete_with_search` | Local path needs an equivalent tool loop |
| 6 | CapIQ screen | Anthropic/Z.ai/OpenRouter web | Phase 1 research is the critical path |
| 7 | Portfolio | Debate Anthropic web; DeepSeek universe **deletes tools** | Must stop dropping tools + attach this search |
| 8 | PI reviews/IR/RFW | Direct SerpAPI | Same `organic_results` contract |

**Hardcoded blocker:** PI `call_deepseek.py:72` `DEEPSEEK_BASE_URL = "https://api.deepseek.com"` — env is ignored. Router README is wishful. First wiring change is there.

**Opt-in blocker:** Setting base URL to the router does **not** enable search. Caller must send `phoenician_tools: ["web_search"]` or we change the router default for Flash.

---

## 4. Contracts to implement (copy these, do not invent)

### 4.1 Router-managed tool (already in production code)

Request extra (stripped before vLLM):

```json
{ "model": "deepseek-v4-flash", "messages": [...], "phoenician_tools": ["web_search"] }
```

Tool the model sees:

```json
{
  "type": "function",
  "function": {
    "name": "web_search",
    "description": "Search the web across multiple providers and return the raw results (title, snippet, link). Results are not pre-filtered — weigh and cross-check them yourself.",
    "parameters": {
      "type": "object",
      "properties": { "query": { "type": "string" } },
      "required": ["query"]
    }
  }
}
```

Loop: max **3** rounds, same Brain, no stream+tools. Return `phoenician_tool_trace` + `phoenician_usage_total`.

**Must change:** do not say “answer from your own knowledge.” Research callers treat that as a bug. Return a hard error string the model cannot treat as facts.

**Must add:** optional `fetch_url` tool (or search that auto-fetches top N). Schema should stay OpenAI function-calling so vLLM Flash can emit `tool_calls`.

### 4.2 SerpAPI-shaped hits (Earnings + PI scrapers)

Callers already parse:

```
GET /search?q=...&engine=google&api_key=...
→ { "organic_results": [ { "title", "snippet", "link", "position?" } ] }
```

Timeouts in the wild: 15s (router), 25–30s (PI), 3 retries + exp backoff (Earnings/EP).

If we expose a drop-in, either wrap SerpAPI or **emulate this JSON**. Earnings `search.py` is “deliberately dumb” — judgment is in `ranker.py`.

### 4.3 PI Perplexity prefetch shape

`fetch_company_web_data` returns prose + citations:

```
Web response: <analyst text>

Citations (use these URLs for hyperlinks):
[SOURCE: Web Citation 1]
[PUBLIC_URL: https://...]
```

Section prompts: `templates/research/web_search_prompt_section{2-8}.jinja`. Missing key **raises**. Cheap shim must **force** web (`force_web_search=True` on Perplexity/RFW shims; prefetch shim currently does **not** force — fix that when wiring).

### 4.4 Anthropic web tool (what we replace, not what we speak)

```json
{ "type": "web_search_20250305", "name": "web_search", "max_uses": N }
```

N in the wild: screening 1–25 (analyst 4, memo 2, intl 25); CapIQ chat 2–3, screen research 8, auditor 6; portfolio debate 5.

Local Flash does not run this server tool. We must execute search ourselves.

### 4.5 DeepSeek cheap web

Responses API `{"type":"web_search"}`. `force_web_search` → `tool_choice` required. Timeout default 360s. Offline fallback **on** for writers, **off** for research (`allow_offline_fallback = not force_web_search`). Prompt hard limit exists — do not dump whole pages untrimmed.

---

## 5. Query patterns the engine will be asked to run

Do not only accept a bare company name. Existing query builders:

**Earnings `build_simple_queries`** (`summary/search.py`):

- `"Company" "2Q26" filetype:pdf`
- `"TICKER" earnings 2026 filetype:pdf`
- `site:ir.example.com earnings`
- Aggressive, few queries, no 37-template explosion

**PI RFW preflight** (`rfw_serp.py`): max 2 queries

- `"Name" TICKER (short seller OR "bear case" OR investigative OR substack OR "Bear Cave")`
- `site:substack.com "Name"`

**PI reviews:** `site:trustpilot.com Company`, Reddit discussion queries (Haiku hints keywords first).

**Screening analyst** (4 searches): moat, trajectory, bear case, valuation.

**CapIQ Phase 1:** research brief from `screen.research.*.j2` — model writes its own queries via the tool.

**Support operators:** `"quotes"`, `site:`, `filetype:pdf`, `OR`, ticker + legal-suffix stripping.

---

## 6. What “good” means per product

| Product | Snippets enough? | Needs fetch? | Needs PDF text? | Needs citations? |
|---|---|---|---|---|
| ai-router today | yes (weak) | no | no | no |
| PI section writing | no | yes (vendor does it) | via RAG already | yes `[PUBLIC_URL]` |
| PI prefetch / RFW / TAM | no | yes | nice | yes |
| PI Trustpilot/Reddit/IR | search only finds URL | scrape is separate | no | no |
| Earnings ranker | search finds candidates | **yes** — ranker reads fetched docs | **yes** | implicit |
| Earnings news Gemini | no | grounding URLs + live check | no | yes |
| Screening analyst/memo | vendor-quality | yes | filings via other ingest | evidence strings |
| CapIQ Phase 1 brief | no | yes | helpful | yes |
| CapIQ verdict | no if brief exists | no | no | no |
| Portfolio debate | maybe | better with fetch | no | citations optional |
| dcf--app | Gemini search | n/a | n/a | JSON fields |

**Rule:** snippets-only will fail DD, CapIQ research, and Earnings. Build fetch+extract from day one.

---

## 7. Fail policy the engine must expose (do not pick one globally)

Callers already disagree. Support a flag, e.g. `on_empty: error | empty | degrade`.

| Mode | Who needs it |
|---|---|
| **error** (raise / tool error, no invented facts) | PI capacity (“not disclosed” is the *writer’s* job, not the search layer inventing %), IPO miss cache, Earnings extract null, DCF, `force_web_search` |
| **empty hits** | RFW preflight skip, auditor null, EP Claude battery continue |
| **degrade to next candidate** | Earnings ranker |
| **never “answer from memory”** | all research — current router string is forbidden |

Default for this engine: **error**. Opt-in empty for scrapers.

---

## 8. Timeouts, concurrency, retries (copy the existing numbers)

| Path | Timeout | Retries |
|---|---|---|
| Router search per provider | 15s | none (skip provider) |
| Router LLM | 300s | none / no Brain failover |
| PI SerpAPI helper | 30s | — |
| PI IR email | 25s | — |
| PI Perplexity | 360s typical | 3 + cheaper sonar chain |
| PI DeepSeek web | 360s (env) | 3 × (5,15,45)s |
| Earnings SerpAPI | ~ | 3, exp backoff base 2 |
| Earnings news Gemini | 120s semaphore | 1 stricter retry if no grounding |
| Screening IR monitor | 45s | — |
| CapIQ Dreams poll | 90 min | n/a |
| Tool rounds | 3 | sequential tool_calls |

Rate limits: screening keeps LLM concurrency at 3; CapIQ screen `SCREEN_CONCURRENCY=5`; SerpAPI quotas are the real budget (PI comments: 100 free / 5k at $50).

---

## 9. What this engine must NOT replace

Leave these as they are. They are data, not “internet search.”

- CapIQ (Selenium, credentials)
- AlphaSense (login + PDF RAG)
- Vertex / Gemini File Search (internal corpus)
- OpenAI embeddings / pgvector
- FMP / yfinance prices
- OpenAI TTS
- Investor-portal PDF extract
- Linker qualitative score (no web)

---

## 10. Recommended service shape

OpenAI-compatible is optional. A small HTTP API is enough if the router calls it:

```
POST /v1/search
  { "query": "...", "num_results": 8, "operators_ok": true }
  → { "query", "hits": [ { "title", "url", "snippet", "source", "date?" } ], "provider" }

POST /v1/fetch
  { "url": "...", "max_chars": 20000 }
  → { "url", "title", "text", "content_type", "ok" }

POST /v1/research   (optional composite)
  { "query": "...", "fetch_top": 5, "max_chars_per_page": 8000 }
  → { "query", "hits", "pages": [ { "url", "title", "excerpt" } ] }
```

Plus the existing `web_search` function tool so Flash can stay in the router loop.

Auth: reuse `ROUTER_API_KEY` or a dedicated `SEARCH_API_KEY`. No tenants today.

---

## 11. Env the engine will see

Search: `SERPAPI_KEY`, `SERPAPI_API_KEY`, `TAVILY_API_KEY`, later self-hosted (SearXNG etc.).  
Must not require `PI_DD`, Anthropic, Perplexity, Gemini to function — those are what we are removing.  
May *use* SerpAPI/Tavily as backends until a local index exists.

---

## 12. Wiring checklist (product repos, later)

1. `call_deepseek.py` — read `DEEPSEEK_BASE_URL` from env.
2. Cheap `fetch_company_web_data` shim — `force_web_search=True`.
3. ai-router `run_web_search` — HTTP to this engine; fail closed.
4. Add `fetch_url` to `_KNOWN_TOOLS`.
5. Portfolio DeepSeek — stop `del tools`; attach `web_search`.
6. Earnings `SearchEngine` — point at `/v1/search` or keep SerpAPI until quality matches.
7. Screening local path — `complete_with_search` equivalent via router tools.
8. CapIQ DeepSeek desk — do not fall back to Anthropic for web; call this engine.

---

## 13. Quality bar vs current router

| Current ai-router | Required |
|---|---|
| 5 snippets, no fetch | fetch top N + extract |
| no dedup / rank | dedup by URL, keep sources labeled |
| no PDF | PDF text for Earnings |
| 3 rounds | 3 is OK if fetch is a tool |
| stream+tools forbidden | still OK for v1; PI cheap is non-stream |
| “answer from knowledge” | forbidden |
| no `site:` awareness | pass query through raw |

---

## 14. Evidence index

| Topic | File |
|---|---|
| **Surgical fetch/SERP fields (this pass)** | `engine-surgical.md` |
| LLM call logic | `logic-01` … `logic-05` |
| SerpAPI / Tavily / FMP / CapIQ | `logic-06-external-apis.md` |
| First-pass map | `llm-audit.md` |
| Integration rules | `.cursor/rules/03-integration.mdc` |
| Router tool | `org-repos/ai-router/app/tools/web_search.py` |
| Cheap web | `org-repos/phoenician-intelligence/src/services/llm_clients/call_deepseek.py` |
| Prefetch | `org-repos/phoenician-intelligence/src/services/web_search.py` |
| Earnings queries | `org-repos/Earnings_tracker/tracker/summary/search.py` |
| Earnings fetch ladder | `org-repos/Earnings_tracker/tracker/summary/fetch.py` |
