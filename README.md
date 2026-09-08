# local-engine-internet

Internet search + fetch for Phoenician Capital local LLMs. Other apps plug in by changing a base URL — no new protocol.

Inference stays on `ai-router`. This service is internet only (`:8090`).

## Install (for any teammate)

You need Python 3.12 and at least one search key. **SerpAPI alone is enough.** Tavily and Brave join automatically when you paste their keys.

```bash
git clone https://github.com/phoenician-capital/local-engine-internet.git
cd local-engine-internet
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Open `.env` and set `SERPAPI_KEY=...`. Optionally also `TAVILY_API_KEY` and `BRAVE_API_KEY`. Then:

```bash
python -m engine
```

In a second terminal, from the same repo with the venv on:

```bash
python scripts/check_search.py
```

You are done when that prints `check_search ok` and `GET http://127.0.0.1:8090/` shows `search_ready: true`. Interactive API: http://127.0.0.1:8090/docs

**Docker (closest to a one-command plugin):**

```bash
cp .env.example .env    # paste SERPAPI_KEY
docker compose up --build
```

```bash
# even shorter, from the repo:
sh scripts/install.sh
python -m engine setup    # creates .env if missing, prints plug-in snippets
python -m engine          # start
python -m engine check    # live search test
```

Search does **not** need a Brain or Playwright. Chat-with-search (Mode 2) needs `UPSTREAM_LLM_BASE_URL` pointing at ai-router **or any OpenAI-compatible LLM**.

## Plug into your LLM

This is an OpenAI-compatible server. Other people do **not** install a plugin inside Cursor/Claude — they change the **base URL** of the client they already have. Search tools are injected automatically (`policy: auto`). No `phoenician_tools` field required.

We serve both URL shapes because clients disagree:

| Client | Set this |
|---|---|
| OpenAI Python / Node, Cursor, Continue, Open WebUI, LiteLLM | `http://127.0.0.1:8090/v1` |
| DeepSeek official SDK / PI `DEEPSEEK_BASE_URL` | `http://127.0.0.1:8090` |
| Raw search (no LLM) | `POST http://127.0.0.1:8090/v1/search` |

`GET /v1/models` is implemented (Cursor / Open WebUI probe this first). `GET /` and `GET /v1` print the same snippets.

**OpenAI Python**

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8090/v1", api_key="local")
print(client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "What did Nvidia report last quarter?"}],
).choices[0].message.content)
```

**Environment (any OpenAI-compatible app)**

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8090/v1
export OPENAI_API_KEY=local
export DEEPSEEK_BASE_URL=http://127.0.0.1:8090
```

**Cursor** — Settings → Models → OpenAI-compatible → Base URL `http://127.0.0.1:8090/v1`, API key `local`, model `deepseek-v4-flash`.

**Continue.dev** — `provider: openai`, `apiBase: http://127.0.0.1:8090/v1`, `useLegacyCompletionsEndpoint: false`.

**LiteLLM** — `api_base: http://127.0.0.1:8090/v1`, `model: openai/deepseek-v4-flash`.

Chat needs a Brain (or another OpenAI-compatible upstream) at `UPSTREAM_LLM_BASE_URL`. If that host is down, chat returns 502 with a hint; **search still works**.

---

Local DeepSeek Brains cannot search the web. Cloud models do that today via vendor tools (Anthropic `web_search_20250305`, Gemini GoogleSearch, Perplexity Sonar, DeepSeek cloud `web_search`). This service is the replacement.

## Mode 1 vs Mode 2

There are two ways the org touches the internet. They stay separate in code and in the API.

| Mode | Who decides | Entry point | Typical callers |
|---|---|---|---|
| **1 — pipeline-directed** | Application code already knows it needs the web. The LLM is not in this loop. | `POST /v1/search`, `POST /v1/fetch`, `POST /v1/research`, `GET /search` | Earnings ranker, EP `smart_finder`, PI Trustpilot/Reddit/IR scrapers |
| **2 — LLM-directed** | The model decides mid-answer to search or fetch. This is the product. | `POST /v1/chat/completions` (OpenAI-compatible agentic loop in front of `ai-router`) | PI cheap path, portfolio DeepSeek, screening / CapIQ local desks |

Same search providers and fetch ladder underneath. Different entry points. Never mixed.

```
apps  →  local-engine-internet :8090  →  ai-router :8080  →  vLLM Flash
              │
              ├─ /v1/chat/completions   Mode 2 tool loop
              ├─ /v1/search|/v1/fetch|/v1/research   Mode 1
              └─ GET /search            SerpAPI-shaped drop-in
```

Apps change `DEEPSEEK_BASE_URL` to this engine. Default policy is `auto`: the model gets `web_search`, `fetch_url`, and `search_and_read` and uses them when needed. Set `phoenician_web.policy` to `off` for a plain pass-through.

## Hard prerequisite: the Brain must emit tool calls

`ai-router` today launches vLLM without tool parsing. Flash will not produce structured `tool_calls` until the Brain is started with:

```
--tokenizer-mode deepseek_v4
--tool-call-parser deepseek_v4
--enable-auto-tool-choice
--reasoning-parser deepseek_v4
```

`GET /capabilities` runs a startup canary against upstream and reports `brain_tool_calls_supported`. Treat the engine as **not done** until that is `true` on the real Brain.

Known compensations already in this repo:

- Tool loop is **non-streaming**. `stream:true` + tools → HTTP 400 (same rule as ai-router).
- **DSML fallback**: if `tool_calls` is empty but `content` contains `<｜DSML｜invoke name="web_search">…` (or DeepSeek `tool▁calls` markup), the call is recovered.
- Streaming pass-through is allowed only with `phoenician_web.policy: "off"`.

## Tools the model sees

OpenAI function-calling (what vLLM Flash emits):

| Tool | What it does |
|---|---|
| `web_search(query, num_results=8, recency_days?)` | Fan-out search. Labeled hits (`title` / `snippet` / `url` / `source` / `kind`). |
| `fetch_url(url, max_chars=8000)` | Fetch + extract. Header is `[PUBLIC_URL: url]`. |
| `search_and_read(query, top_n=3)` | Search then fetch top hits in one round (saves Flash rounds). |

Request extras (stripped before upstream):

```json
{
  "model": "deepseek-v4-flash",
  "messages": [{"role": "user", "content": "…"}],
  "phoenician_tools": ["web_search", "fetch_url", "search_and_read"],
  "phoenician_web": {
    "policy": "auto",
    "max_search_uses": 8,
    "max_fetches": 8,
    "max_rounds": 6,
    "fetch_mode": "full",
    "domain_mode": "general_research"
  }
}
```

- `policy: auto` — model chooses (default).
- `policy: required` — PI `force_web_search`. If the first turn has no tool call, the engine re-asks once with `tool_choice` forced on `web_search`, then **HTTP 424** if there is still no successful search.
- `policy: off` — pass-through, no tools, no guidance.

Response extras (ai-router shapes plus citations):

- `phoenician_tool_trace` — every tool call
- `phoenician_usage_total` — summed tokens across rounds
- `phoenician_sources` — `{title, url, date?, source}` actually returned
- `phoenician_citations_block` — both PI forms: `[SOURCE: Web Citation N]` / `[PUBLIC_URL:]` and `[SOURCE: title (Date: …)]` / `[PUBLIC_URL:]`
- `phoenician_search_failed` — `true` when a provider failed

## Mode 1 primitives

```
POST /v1/search   {query, num_results, providers?, domain_mode?, recency_days?}
                  → {query, hits, providers_used}

POST /v1/fetch    {url, max_chars, mode, domain_mode}
                  → {url, final_url, title, text, content_type, is_pdf, tier, ok, error}

POST /v1/research {query, fetch_top, max_chars_per_page}
                  → {query, hits, pages}

GET  /search?q=&engine=google&num=
                  → {organic_results, answer_box, knowledge_graph, related_questions}
```

`GET /search` is a SerpAPI-shaped drop-in. Earnings / EP / PI scrapers can switch the host and keep parsing `organic_results[]`.

`domain_mode`:

| Mode | Deny list |
|---|---|
| `general_research` (default) | social / spam only |
| `ir_discovery` | PI aggregator list + IR PDF blocklist **including** `sec.gov` |
| `earnings_doc` | social only — **SEC is allowed** (Earnings does fetch EDGAR) |

## Search providers

Every configured provider runs **in parallel**. Results are blended, not first-wins.

| Provider | Env | Role in the mix |
|---|---|---|
| SerpAPI | `SERPAPI_KEY` | Google rank, `site:` / `filetype:`, answer box, knowledge graph, related questions, news |
| Tavily | `TAVILY_API_KEY` | Longer excerpts. Same URL keeps Google as the source and Tavily’s text if it is longer |
| Brave | `BRAVE_API_KEY` | Independent index, extra snippets, news |
| SearXNG | `SEARXNG_URL` | Optional self-hosted |
| Google CSE | `GOOGLE_API_KEY` + `GOOGLE_SEARCH_ENGINE_ID` | Pin-only official-site fallback — **not** in the default mix |

**Best set:** SerpAPI + Tavily + Brave. SerpAPI alone is enough to start. CSE is skip unless you have a working Custom Search project (a suspended consumer key returns 403).

Blend rules:

1. Fan-out all configured default providers at once (15s each, one retry on 429/5xx).
2. Same URL from two providers → one hit: SerpAPI source wins, Tavily snippet wins if it is meaningfully longer, `also_from` lists the others.
3. Organic list is **round-robin** (SerpAPI, Tavily, Brave, SearXNG) so one index cannot fill all 8 slots.
4. Cross-confirmed URLs go first. `search_and_read` fetches those first.
5. One provider failing is skipped. **All failing is an error**, not degraded prose.

`GET /search` still pins SerpAPI when that key exists (Earnings / EP drop-in). `POST /v1/search` and the model tools always mix.

## Fetch ladder

Port of `Earnings_tracker/tracker/summary/fetch.py`:

1. **httpx** with Chrome-like headers + age-gate cookies (`brotli` is required so `Content-Encoding: br` pages decode)
2. On WAF statuses `{401,403,406,409,429,503}` or bot-challenge markers → **curl_cffi** `impersonate="chrome"`
3. Thin HTML (<400 chars) or IR-looking URL → **Playwright** (expanders / tabs / EN+JP+PL labels / spinner wait / `data-pdf` harvest)
4. **PDF** chain: pdfplumber → PyMuPDF → pypdf → pdftotext → regex
5. **SEC** wrapper → EX-99.1 exhibits, compliant User-Agent

`FETCH_MODE=full|no_browser|httpx_only` so the engine can run on a box without Chromium.

Extraction: Trafilatura markdown, then Earnings `html_to_text`. Caps: 8k HTML / 25k PDF. Process-wide URL cache with negative TTL.

## Fail-closed guarantees

Research callers treat “answer from your own knowledge” as a bug. This engine **never** emits that string.

| Situation | Behaviour |
|---|---|
| No search provider configured | Tool result `ERROR: web_search unavailable (…). Do not present unverified facts as sourced.` |
| Every provider fails | Same ERROR string; Mode 1 returns **502** |
| Search / fetch over budget | ERROR string, no invented data |
| `policy: required` and no successful search | **HTTP 424** |
| Empty hits after a successful provider call | Returned as “no results” (not a failure) |

Default for Mode 1 `/v1/search` is `on_empty: empty`. Set `on_empty: error` to 502 on zero hits.

## Run

Same as Quick start: `python -m engine` (reads `.env`, binds `:8090`). Equivalent: `uvicorn engine.main:app --host 0.0.0.0 --port 8090`.

```bash
playwright install chromium   # only if FETCH_MODE=full
```

Docker (Chromium + poppler). Copy `.env.example` to `.env` first if you want keys loaded:

```bash
cp .env.example .env   # then set SERPAPI_KEY
docker compose up --build
# optional self-hosted search:
docker compose --profile searxng up
```

Auth: `Authorization: Bearer $ENGINE_API_KEY`. Unset = open (local use, same as ai-router). `GET /search` also accepts `api_key=` for SerpAPI drop-in.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `ENGINE_HOST` / `ENGINE_PORT` | `0.0.0.0` / `8090` | Bind |
| `ENGINE_API_KEY` | empty | Incoming auth; alias `SEARCH_API_KEY` |
| `UPSTREAM_LLM_BASE_URL` | `http://127.0.0.1:8080` | ai-router |
| `UPSTREAM_API_KEY` | empty | Forwarded as Bearer; alias `ROUTER_API_KEY` |
| `UPSTREAM_MODEL` | `deepseek-v4-flash` | Default model field |
| `SERPAPI_KEY` | | Google SERP — enough alone; best as the Google slot in the mix |
| `TAVILY_API_KEY` | | Longer excerpts (joins the mix when set) |
| `BRAVE_API_KEY` | | Independent index + news |
| `TAVILY_SEARCH_DEPTH` | `advanced` | `basic` or `advanced` |
| `SEARCH_PROVIDER_RETRIES` | `1` | Extra try on 429 / 5xx / timeout per provider |
| `SEARXNG_URL` | | Self-hosted SearXNG |
| `GOOGLE_API_KEY` + `GOOGLE_SEARCH_ENGINE_ID` | | CSE (pin-only; skip if the project is suspended) |
| `FETCH_MODE` | `full` | `full` / `no_browser` / `httpx_only`. Example env defaults to `no_browser`. |
| `MAX_TOOL_ROUNDS` | `6` | Router's 3 is too low once fetch is a tool |
| `MAX_SEARCH_USES` / `MAX_FETCHES` | `8` / `8` | Per-request caps |
| `WEB_CONTEXT_BUDGET_CHARS` | `150000` | PI per-section web inject |
| `MAX_CHARS_PER_DOC` / `MAX_CHARS_PER_PDF` | `8000` / `25000` | Per-document trim |
| `DOC_FETCH_TIMEOUT` | `20` | Seconds |
| `REQUEST_TIMEOUT` | `300` | Upstream LLM |
| `SEC_EDGAR_USER_AGENT` | LocalEngineInternet/1.0 + phoeniciancapital.com | Required by EDGAR |
| `DEFAULT_WEB_POLICY` | `auto` | `auto` / `required` / `off` |
| `RUN_CANARY_ON_STARTUP` | `true` | Brain tool-call probe (background, does not block search) |
| `CANARY_TIMEOUT_SECONDS` | `5` | How long the probe waits for ai-router |

## Wiring other repos (later, not in this repo)

1. **phoenician-intelligence** `src/services/llm_clients/call_deepseek.py` — read `DEEPSEEK_BASE_URL` from env (today it is hardcoded to `https://api.deepseek.com`); point it at this engine. Cheap `fetch_company_web_data` shim → `force_web_search=True` (maps to `policy: required`).
2. **ai-router** `app/tools/web_search.py` — replace the body with `POST /v1/search`; delete the “answer from your own knowledge” fallback.
3. **phoenician-portfolio** `strategy/deepseek.py` — stop `del tools`; send `phoenician_tools` when the provider is local.
4. **Earnings / EP / PI scrapers** — optional: swap `serpapi.com/search` for `GET /search` on this engine (same JSON).
5. **Brain launch** — add the four vLLM flags above.

Do not route `deepseek-v4-pro` to a Flash-only Brain.

## Tests

```bash
pytest
# Mode 1 live (whatever keys are in .env — engine optional):
python scripts/check_search.py
# Mode 2 live (needs a running engine + router + Brain tool-call flags):
python scripts/smoke.py
```

Unit coverage: provider parsers (including `answer_box` / knowledge graph), merge/dedup, query hygiene, ladder tier selection (403 → curl_cffi, thin → Playwright, PDF, SEC exhibits), Trafilatura vs `html_to_text` fallback, DSML recovery, agent loop with mocked upstream, `required` re-ask + 424, budgets, fail-closed strings, SerpAPI-compat shape.

## What this engine does not replace

CapIQ, AlphaSense, Vertex / Gemini File Search, OpenAI embeddings / pgvector, FMP / yfinance, OpenAI TTS. Those are data products, not internet search.
