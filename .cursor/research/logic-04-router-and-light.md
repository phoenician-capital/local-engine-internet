# ai-router + light LLM surfaces — every logic bit

---

## ai-router

Local-only OpenAI proxy. **No cloud LLM fallback.**

```
POST /chat/completions | /v1/chat/completions
  require_router_key (ROUTER_API_KEY; unset = open)
  rate_limit (RATE_LIMIT_PER_MINUTE; 0 = off; key = Authorization or IP)
  reject if stream && phoenician_tools
  estimate_tokens = chars/4
  registry.pick(tokens, X-Priority low|normal|high)
    candidates = healthy + not drained + context fits
    low skips Brain at load >= 1.0
    pick min(load = active / max_concurrent)
    none → 503
  if stream: open_stream, inject stream_options.include_usage, SSE passthrough
  else: run_with_tools → post_completion
    Brain fail → mark unhealthy, 502, NO retry other Brain
```

### Tool loop (`app/tools/orchestrator.py`)

- Pop `phoenician_tools`; keep only names in `_KNOWN_TOOLS` (today: `web_search`)
- Inject OpenAI function schema; `tool_choice` default auto
- `MAX_TOOL_ROUNDS = 3`
- Each tool_call: if `web_search` → `run_web_search`; else “not available”
- Append `role=tool` and re-post **same Brain**
- Response extras: `phoenician_tool_trace`, `phoenician_usage_total`

### web_search (`app/tools/web_search.py`)

- Parallel SerpAPI (`GET serpapi.com/search`, engine=google) + Tavily (`POST api.tavily.com/search`)
- 15s timeout each, **5 results**, title/snippet/link, no fetch/rank/dedup
- Missing key → skip provider
- No providers or all fail → string: **answer from own knowledge**
- Standard `tools` passthrough: caller executes, router does nothing

### Timeouts / brains

`REQUEST_TIMEOUT_SECONDS=300`. Health poll 15s, health HTTP 5s. Brains from `BRAIN_1_URL`… until first missing. Default max_concurrent 64, context 1_048_576. Auth to Brain: `BRAIN_n_API_KEY`. Caller never sees Brain keys.

Admin `/admin/*` requires `ADMIN_API_KEY` (unset → 503). Control URL restart/stop/start → **501**.

---

## Linker (`capiq/analysis/qualitative.py`)

- Anthropic `messages.create`, model `claude-sonnet-4-6` (`CAPIQ_QUALITATIVE_MODEL` override)
- Inline system: JSON `{score, rationale}`, score 0–40
- 3 attempts, backoff `min(20, 2**attempt)`
- Parse regex `{...}` + json.loads, clamp 0–40
- Fail per ticker → None; no key → cache-only
- Workers 8, max_tokens 600
- Cache `data/qualitative_cache.csv` append-only
- CLI: `analyze_capital_allocation.py` `--no-qualitative` skip

---

## investor-portal-backend (`OpenAi*.cs`)

Key: `OpenAI__ApiKey` / secret `phoenician-ai-api-keys`. **Temp 0. No service retries.**

| Class | Model | Vision | Parse |
|---|---|---|---|
| OpenAiNameExtractor | gpt-4o-mini | no | json_object |
| OpenAiStatementSegmenter | gpt-4o-mini | no | structured |
| OpenAiContractNoteExtractor | mini; **gpt-4o** if text fails | yes | json_schema strict + substring checks |
| OpenAiContractNoteTypeVerifier | mini / gpt-4o vision | yes | json_object |
| OpenAiSubscriptionDateExtractor | mini / vision | yes | json_object |
| OpenAiAnnualReportYearExtractor | mini / vision | yes | json_object |

Admin PDF extraction only. Not investor-facing portfolio logic.

---

## dcf--app (`services/gemini.ts`)

- Client-side `GoogleGenAI({ apiKey: process.env.API_KEY })` — key baked by Vite (`GEMINI_API_KEY`)
- Model **`gemini-3-flash-preview`** hardcoded
- Tools: `{ googleSearch: {} }`
- `responseMimeType: application/json`, `thinkingBudget: 0`
- Large JSON schema (financials / unit economics)
- Parse: strip fences → JSON.parse → sanitize millions
- Catch → `null`

Empty sibling repo `dcf-app` has no source.

---

## phoenician-intelligence-backend

| Surface | Model | Notes |
|---|---|---|
| DeveloperController error analysis :190 | haiku-4-5-20251001, max 1024 | direct `api.anthropic.com` |
| Run log analysis :473 | sonnet-4-6, max 1500 | |
| Log chat :723 | sonnet-4-6, max 1500 | |
| TextToSpeechController | **passthrough body model** | key `Open_AI_tts`; max 4096 chars |
| LlmCostService | none | prices Python callbacks |
| Vendor billing adapters | none | Anthropic/OpenAI/DeepSeek/GCP sync |

Frontend: OpenAI TTS `gpt-4o-mini-tts-2025-12-15` (marin/cedar). Chatbot UI proxies Python. No report LLM.

---

## Confirmed no production LLM

`pi-global` (docs/maps only), `phoenician-frontend-kit` (sample cost rows), `phoenician-mail-sender`, `Factsheet-Automation`, `phoenician-capital-website`, `investor-portal-web`, `investor-portal-mobile`, `investor-portal-backend-archive`, `dcf-app` (empty).

---

## Fail-policy cheat sheet

| System | Search/LLM down |
|---|---|
| ai-router tools | tell model to use training data |
| ai-router Brain | 503 / 502, no cloud, no other-Brain retry |
| PI DCF S8 | raise, abort section |
| PI TAM step 2 | continue without research |
| PI CJA | return base section 2 |
| PI chatbot determine-action | action=query |
| PI chatbot stream | SSE error (no Gemini) |
| Screening memo | template memo |
| Screening analyst | Python scores |
| Screening BusinessModelAgent | pass=True |
| Portfolio debate router | keyword heuristic |
| Portfolio trader pace | deterministic participation |
| Linker | skip ticker / cache |
| Earnings classify | rule fallback |
| dcf--app | return null |
