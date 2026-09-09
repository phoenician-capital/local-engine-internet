# local-engine-internet

A local HTTP service that gives Phoenician apps **search** and **page fetch**. It does not run the LLM. It sits in front of `ai-router` (the Brain) and in front of any script that already decided it needs the web.

**Full write-up (read this):** [docs/method.html](docs/method.html)

- Listens on **`:8090`**
- Inference stays on **ai-router `:8080`** → vLLM Flash
- Apps keep speaking **OpenAI chat-completions**. They change the base URL. They do not install a Cursor/Claude plugin.

Local DeepSeek cannot search. Cloud models do that today with vendor tools (Anthropic `web_search`, Gemini Google Search, Perplexity Sonar, DeepSeek cloud `web_search`). This service is the replacement for that missing piece only.

---

## What it does not do

It is not an inference proxy. It does not replace CapIQ, AlphaSense, Vertex / Gemini File Search, pgvector RAG, FMP, yfinance, or TTS. Those are other products.

It never tells the model to “answer from your own knowledge.” If search is required and it fails, the caller gets an error.

---

## How the boxes connect

```
your app
   │
   │  OpenAI chat, or raw search JSON
   ▼
local-engine-internet :8090
   │
   ├── Mode 1  POST /v1/search  /v1/fetch  /v1/research
   │           GET  /search          (SerpAPI-shaped JSON)
   │           → SerpAPI / Tavily / Brave / SearXNG, then optional fetch
   │
   └── Mode 2  POST /v1/chat/completions
               → tool loop here (search / fetch)
               → ai-router :8080 → vLLM Flash
```

Two entry points. Same search and fetch underneath. They are never mixed in one request.

| | Who decides to go online | Needs a Brain? | Needs a search key? |
|---|---|---|---|
| **Mode 1** | Your code. The LLM is not in this loop. | No | Yes |
| **Mode 2** | The model, mid-answer (unless you force it). | Yes (`UPSTREAM_LLM_BASE_URL`) | Yes |

Toggle and status: http://127.0.0.1:8090/ui  
OpenAPI: http://127.0.0.1:8090/docs  
Welcome JSON: http://127.0.0.1:8090/

---

## The internet plugin (two layers)

This is the only product switch that matters.

### Layer 1 — on or off

Master switch. When **off**:

- `POST /v1/search`, `/v1/fetch`, `/v1/research`, `GET /search` → **HTTP 503**
- Chat still works. It is a plain pass-through to the Brain. No tools. No search. No fetch.

When **on**, layer 2 applies.

How to flip it:

| Where | What |
|---|---|
| http://127.0.0.1:8090/ui | Button |
| `POST /v1/plugin` `{"enabled": true\|false}` | Same switch, no restart |
| `PLUGIN_ENABLED` in `.env` | Value at process start |
| `phoenician_web.enabled: false` on one chat request | Off for that request only |
| Header `X-Phoenician-Plugin: off` | Off for that request only |

**Global off always wins.** A request cannot force the plugin on if the master switch is off.

`GET /v1/plugin` returns `{enabled, intelligence, providers, search_ready}`.

`search_ready` is true only when at least one search key is configured **and** the plugin is on.

### Layer 2 — intelligence (only if layer 1 is on)

The **model** decides whether *this* question needs the live web. That is `policy: auto`.

- “What is 2+2?” — it should answer without searching.
- “What did Nvidia report last quarter?” — it should call `web_search` (and often `fetch_url`).

Research desks can override per request:

| `phoenician_web.policy` | Meaning |
|---|---|
| `auto` (default) | Model chooses. Tools are available. |
| `required` | Must search. If the first turn has no tool call, the engine re-asks once with `tool_choice` forced on `web_search`. Still no successful search → **HTTP 424**. |
| `off` | Plugin stays on, but this request is pass-through (no tools). Use this for streaming. |

`phoenician_tools: []` also means pass-through (opt out of tools).

---

## Mode 1 — your code already wants the web

No LLM. You send a query or a URL. You get JSON.

### Search

`POST /v1/search`

```json
{"query": "Phoenician Capital", "num_results": 8}
```

Returns `hits[]` (`title`, `url`, `snippet`, `source`, `kind`, `also_from`), `providers_used`, `errors`, `confirmed` (URLs seen by more than one provider).

Optional: `providers`, `domain_mode`, `recency_days`, `on_empty` (`empty` default, or `error` → 502 on zero hits).

### Fetch

`POST /v1/fetch`

```json
{"url": "https://example.com", "max_chars": 8000}
```

Returns the extracted page: `title`, `text`, `final_url`, `is_pdf`, `tier`, `ok`, `error`.

### Search then fetch

`POST /v1/research`

Search, then fetch the top organic URLs (cross-confirmed first). Returns `hits` and `pages`.

### SerpAPI drop-in

`GET /search?q=Phoenician+Capital&num=5`

Same shape Earnings / EP / PI scrapers already parse: `organic_results`, `answer_box`, `knowledge_graph`, `related_questions`.

This path **pins SerpAPI** when that key exists (so answer box / knowledge graph survive). `/v1/search` and the model tools always **mix** every configured provider.

If the plugin is off, all of the above return **503**.

---

## Mode 2 — the model decides mid-answer

This is chat with tools, in front of the Brain.

1. Client sends a normal OpenAI body to `POST /v1/chat/completions` (or `/chat/completions` — both exist because SDKs disagree on `/v1`).
2. Engine checks layer 1 and layer 2.
3. If the plugin is off, or `policy` is `off`, or `phoenician_tools` is `[]`:
   - `phoenician_*` fields are stripped
   - our search tools are stripped
   - the body is forwarded to `UPSTREAM_LLM_BASE_URL` unchanged
4. If the plugin is on and policy is `auto` or `required`:
   - the engine injects three OpenAI tools: `web_search`, `fetch_url`, `search_and_read`
   - it prepends system rules: search when facts may have changed; do not invent URLs; treat `ERROR:` as failure
   - it calls the Brain
5. If the Brain returns `tool_calls` (or DSML markup in `content` that we recover):
   - the engine runs those tools
   - it appends `role: tool` messages
   - it calls the Brain again
   - repeat, up to `MAX_TOOL_ROUNDS` (default 6)
6. When the Brain answers in prose, that response goes back to the client, plus extras:

| Field | Meaning |
|---|---|
| `phoenician_plugin` | `{enabled, intelligence, searched}` |
| `phoenician_tool_trace` | Every tool call |
| `phoenician_sources` | URLs actually returned |
| `phoenician_citations_block` | `[SOURCE: …]` / `[PUBLIC_URL: …]` (both PI shapes) |
| `phoenician_search_failed` | A provider failed |
| `phoenician_usage_total` | Tokens summed across rounds |

Streaming (`stream: true`) **cannot** run the tool loop. HTTP **400** if the plugin would inject tools. Stream is allowed only as pass-through (plugin off or `policy: off`).

If the Brain is down, chat is **502**. Mode 1 search still works if the plugin is on.

### Tools the model can call

| Tool | What happens |
|---|---|
| `web_search(query, num_results=8, recency_days?)` | Parallel mix. Labeled hits. The model weighs them. |
| `fetch_url(url, max_chars=8000)` | Fetch + extract. First line is `[PUBLIC_URL: url]`. |
| `search_and_read(query, top_n=3)` | Search, then fetch the top organics (confirmed URLs first). |

Optional extras on the chat body (stripped before the Brain sees them):

```json
{
  "model": "deepseek-v4-flash",
  "messages": [{"role": "user", "content": "What did Nvidia report last quarter?"}],
  "phoenician_web": {
    "enabled": true,
    "policy": "auto",
    "max_search_uses": 8,
    "max_fetches": 8,
    "max_rounds": 6,
    "fetch_mode": "no_browser",
    "domain_mode": "general_research"
  }
}
```

You do **not** need `phoenician_tools` for the default path. The engine injects all three tools when the plugin is on.

### The Brain must emit tool calls

vLLM Flash will not produce structured `tool_calls` unless it was started with:

```
--tokenizer-mode deepseek_v4
--tool-call-parser deepseek_v4
--enable-auto-tool-choice
--reasoning-parser deepseek_v4
```

`GET /capabilities` reports `brain_tool_calls_supported` after a short startup probe. Mode 1 does not care about this. Mode 2 does.

If the model writes DeepSeek DSML in `content` instead of `tool_calls`, the engine recovers it.

---

## Search mix

Every key you set is used **in parallel**. Results are blended. Not first-wins.

| Provider | Env | What it adds |
|---|---|---|
| SerpAPI | `SERPAPI_KEY` | Google rank, `site:` / `filetype:`, answer box, knowledge graph, related questions, a little news. Enough alone. |
| Tavily | `TAVILY_API_KEY` | Longer excerpts. |
| Brave | `BRAVE_API_KEY` | Independent index + news. |
| SearXNG | `SEARXNG_URL` | Optional self-hosted. |
| Google CSE | `GOOGLE_API_KEY` + `GOOGLE_SEARCH_ENGINE_ID` | Pin-only. Not in the default mix. Skip if the Custom Search project is suspended (403). |

What happens on one query:

1. All default configured providers run at once (15s each, one retry on 429 / 5xx / timeout).
2. Same URL from two providers → one hit. SerpAPI stays `source`. If Tavily’s snippet is meaningfully longer, that text is kept. `also_from` lists the others.
3. Organics are **round-robin** (SerpAPI, Tavily, Brave, SearXNG) so one index cannot fill all eight slots.
4. URLs seen by more than one provider go first. `search_and_read` and `/v1/research` fetch those first.
5. One provider failing is skipped and listed in `errors`. **Every** provider failing is an error (Mode 1 → **502**; the model sees `ERROR: web_search unavailable (…). Do not present unverified facts as sourced.`).

Zero hits after a successful provider call is “no results”, not a failure.

### Domain filters (`domain_mode`)

Applied to hits and fetches.

| Mode | Dropped |
|---|---|
| `general_research` (default) | Social / spam |
| `ir_discovery` | PI aggregator list + IR PDF blocklist, **including** `sec.gov` |
| `earnings_doc` | Social only. **SEC is allowed** (Earnings fetches EDGAR). |

---

## Fetch ladder

How a URL becomes text:

1. **httpx** — Chrome-like headers, age-gate cookies. Brotli is installed so `Content-Encoding: br` pages decode.
2. WAF / bot-challenge (`401, 403, 406, 409, 429, 503` or challenge HTML) → **curl_cffi** Chrome impersonation.
3. Thin HTML (<400 characters) or an IR-looking URL → **Playwright** (only if `FETCH_MODE=full`).
4. **PDF** — pdfplumber → PyMuPDF → pypdf → pdftotext → regex.
5. **SEC** wrappers — EX-99.1 exhibits, EDGAR User-Agent.

`FETCH_MODE`:

| Value | Use |
|---|---|
| `no_browser` (`.env.example`) | Search + static HTML/PDF. No Chromium. |
| `httpx_only` | No curl_cffi, no Playwright. |
| `full` | Needs `playwright install chromium`. JS IR pages. |

HTML extract: Trafilatura markdown, then a simple HTML-to-text fallback. Caps: 8k characters HTML, 25k PDF. Process-wide URL cache (failures cached for a short time too).

---

## Fail-closed

| Situation | What you get |
|---|---|
| No search key | Tool: `ERROR: …`. Mode 1: **502** |
| Every provider fails | Same |
| Over search/fetch budget | `ERROR: … budget exhausted` |
| `policy: required` and no successful search | **HTTP 424** |
| Plugin off | Mode 1 **503**. Chat pass-through |
| Empty query / bad tool arguments | `ERROR:` string, not a 500 |
| Empty hits after a live provider | “No results” |

The string “answer from your own knowledge” is never emitted.

---

## Point a client at it

| Client | Base URL |
|---|---|
| OpenAI Python / Node, Cursor, Continue, Open WebUI, LiteLLM | `http://127.0.0.1:8090/v1` |
| DeepSeek SDK / PI `DEEPSEEK_BASE_URL` | `http://127.0.0.1:8090` (no `/v1`) |
| Raw search | `POST http://127.0.0.1:8090/v1/search` |

API key: `local` if `ENGINE_API_KEY` is empty. If you set a key, send `Authorization: Bearer …`. `GET /search` also accepts `api_key=` (SerpAPI drop-in).

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8090/v1", api_key="local")
print(client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "What did Nvidia report last quarter?"}],
).choices[0].message.content)
```

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8090/v1
export OPENAI_API_KEY=local
export DEEPSEEK_BASE_URL=http://127.0.0.1:8090
```

`GET /v1/models` exists because Cursor and Open WebUI probe it first.

**PI note:** `call_deepseek.py` still hardcodes `DEEPSEEK_BASE_URL = "https://api.deepseek.com"`. Pointing env at this engine does nothing until that line reads the environment.

Do not send `deepseek-v4-pro` to a Flash-only Brain.

---

## Run it

Python 3.12. One search key is enough (`SERPAPI_KEY`). Tavily and Brave join when you add their keys.

```bash
git clone https://github.com/phoenician-capital/local-engine-internet.git
cd local-engine-internet
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# put SERPAPI_KEY= in .env
python -m engine
```

Second terminal:

```bash
python scripts/check_search.py
```

That should print `check_search ok`. Then `GET /` should show `search_ready: true`.

Same thing: `sh scripts/install.sh` then `python -m engine setup` / `run` / `check`.

Docker:

```bash
cp .env.example .env   # set SERPAPI_KEY
docker compose up --build
```

`FETCH_MODE=full` also needs:

```bash
playwright install chromium
```

Auth is off when `ENGINE_API_KEY` is empty (local, same as ai-router).

---

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `ENGINE_HOST` / `ENGINE_PORT` | `0.0.0.0` / `8090` | Bind |
| `ENGINE_API_KEY` | empty | Incoming auth (`SEARCH_API_KEY` alias) |
| `PLUGIN_ENABLED` | `true` | Layer 1 at startup |
| `DEFAULT_WEB_POLICY` | `auto` | Layer 2: `auto` / `required` / `off` |
| `UPSTREAM_LLM_BASE_URL` | `http://127.0.0.1:8080` | Brain (Mode 2 only) |
| `UPSTREAM_API_KEY` | empty | Forwarded as Bearer (`ROUTER_API_KEY` alias) |
| `UPSTREAM_MODEL` | `deepseek-v4-flash` | Default `model` field |
| `SERPAPI_KEY` | | Google SERP — enough alone |
| `TAVILY_API_KEY` | | Longer excerpts |
| `BRAVE_API_KEY` | | Independent index |
| `SEARXNG_URL` | | Self-hosted |
| `GOOGLE_API_KEY` + `GOOGLE_SEARCH_ENGINE_ID` | | CSE, pin-only |
| `TAVILY_SEARCH_DEPTH` | `advanced` | `basic` or `advanced` |
| `SEARCH_PROVIDER_RETRIES` | `1` | Extra try on 429 / 5xx / timeout |
| `FETCH_MODE` | `full` in code, `no_browser` in `.env.example` | `full` / `no_browser` / `httpx_only` |
| `MAX_TOOL_ROUNDS` | `6` | Mode 2 rounds |
| `MAX_SEARCH_USES` / `MAX_FETCHES` | `8` / `8` | Per request |
| `WEB_CONTEXT_BUDGET_CHARS` | `150000` | Old tool text is compacted when over this |
| `MAX_CHARS_PER_DOC` / `MAX_CHARS_PER_PDF` | `8000` / `25000` | Per page |
| `DOC_FETCH_TIMEOUT` | `20` | Seconds |
| `SEARCH_PROVIDER_TIMEOUT` | `15` | Seconds |
| `REQUEST_TIMEOUT` | `300` | Brain call |
| `SEC_EDGAR_USER_AGENT` | LocalEngineInternet + phoeniciancapital.com | Required by EDGAR |
| `RUN_CANARY_ON_STARTUP` | `true` | Background tool-call probe |
| `CANARY_TIMEOUT_SECONDS` | `5` | Probe wait |

---

## Tests

```bash
pytest
python scripts/check_search.py          # live Mode 1; engine optional
python scripts/smoke.py                 # live Mode 2; needs engine + Brain + vLLM flags
```
