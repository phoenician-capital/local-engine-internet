# PI — every LLM logic bit

Paths under `org-repos/phoenician-intelligence/`. Cheap path = `src/core/workflow_deepseek.py` patches before importing `workflow.py`.

---

## Shared retry (`src/services/llm_clients/_retry.py`)

`call_with_retry_and_fallback`:
- 3 primary attempts, delays `(5, 15, 45)s` + 0–20% jitter
- Then **exactly 1** attempt on `cheaper_model` if errors were retryable
- Non-retryable: auth, most 4xx except 429 → raise immediately
- Streaming: rebuild full request each attempt

Used by Claude, Gemini, OpenAI, Grok, Perplexity wrappers. **Not** used by DeepSeek `_call_raw` or `call_dcf_llm_with_retry`.

---

## Fallback manager (`llm_client_manager.py`)

| Function | Model | Key | Logic |
|---|---|---|---|
| `call_claude_with_config` :52 | `claude-sonnet-4-6`, max 8000, temp 1.0, timeout 300 | `PI_DD` | `messages.create`, text strip, no fallback |
| `call_claude_with_config_chatbot` :100 | same | `PI_CHATBOT` | same |
| `call_gemini_with_config` :143 | `gemini-2.5-pro`, temp 0.0 | `GEMINI_API_KEY` | `response.text` |
| `generate_with_fallback` :194 | Claude then Gemini | PI_DD | 3 Claude retries (exp backoff cap 60s) → 3 Gemini → raise |
| `generate_with_fallback_chatbot` :277 | same | PI_CHATBOT | used by n8n query/modify/suggest |

Production DD does **not** use `generate_with_fallback`. Chatbot sync Q&A does.

---

## Claude wrappers (`call_claude.py`) — key `PI_DD` unless noted

| Function | Model / params | Tools / cache | Fallback | Callers |
|---|---|---|---|---|
| `call_claude` :343 | Sonnet 4.6, max 64k, timeout 1800, skills system | none | cheaper-model chain | TAM synthesis |
| `call_claude_deterministic` :376 | Sonnet 4.6, **temp 0**, max 16k | none | same | RFW synthesis |
| `call_claude_chatbot` :409 | Sonnet 4.6, max 64k | none | same | notes + agentic synth; **PI_CHATBOT** |
| `call_claude_thinking` :438 | Opus 4.6, max 128k, `thinking.adaptive` | none | same | competitor rank |
| `call_claude_sonnet_query` :554 | Sonnet 4.6, max 2000 | optional ephemeral cache | same | CIO lens, agentic queries, evaluator |
| `call_claude_writing` :621 | Sonnet 4.6, max 65536, **temp 0**, **stream** | optional cache; skills after cache | 3× Claude → **1× gemini-2.5-pro** | S1, S4, S5, S8 exec, ACS, CJA, TIW |
| `call_claude_haiku` :851 | `claude-haiku-4-5-20251001`, max 16384, temp 0 | none | same | reviews, lab |
| `call_claude_writing_web` :881 | Sonnet 4.6, stream, max 65536 | **`web_search_20250305`**, optional cache | 3× sonnet → 1× **haiku-4-5** | S2,S3,S6,S7,S9,S8.5 |
| `call_claude_streaming_with_thinking` :1005 | Opus 4.6 default, max 128k, thinking_budget 10000 (0 = off, temp 0), effort low–max | cache optional | delays (30,60,120)s | DCF, cashflow, repetition |
| `call_claude_web` :1275 | Opus 4.6, max 8096, stream | `web_search_20250305` | same | IR URL discovery |
| `call_claude_web_chatbot` :1334 | same | same | same | agentic_query web; **PI_CHATBOT** |
| `call_claude_sonnet_batch` :1394 | Sonnet 4.6, Batch API 50% off, poll 5–30s, timeout 300 | per-req cache | failed id → None | query prefetch, repetition P2 |
| `call_claude_risk_auditor_cached` :1787 | caller Opus, temp 0.2, timeout 600 | **2 cache breakpoints** | caller cheaper | RA Pass 2 |

Parse: text blocks joined. Structured (`call_claude_structured`) exists, **no src callers**. `get_competitors_from_claude_api` (Opus) — **dead**.

---

## Gemini (`call_gemini.py`) — `GEMINI_API_KEY`

| Function | Model | Tools / extras | Failure |
|---|---|---|---|
| `call_gemini` :307 | 2.5-pro, temp 0, max 65536 | explicit cache TTL 300/3600 | 3+1 cheaper; returns **error string** |
| `call_gemini_web` :385 | 2.5-pro | **`GoogleSearch()`** + cache | same |
| `call_gemini_structured` :583 | 2.5-pro | JSON mime + Pydantic; ValidationError re-prompt | CJA steps 1–4 |
| `call_gemini_file_api` :757 | `GEMINI_SEARCH_MODEL` = **2.5-flash-lite**, temp 0.1, max 8192 | optional cache_files | 5 retries, delays (30,60,120) |
| `call_gemini_interactions` :1284 | **gemini-3.6-flash** | `google_search` tool | 3 linear retries; **beta workflow** |

Dead: `gemini_web_revenue`, `call_gemini_deep`, perplexity-tool Gemini helpers.

---

## Perplexity (`call_perplexity.py`) — `PERPLEXITY_API_KEY`

Endpoint `https://api.perplexity.ai/chat/completions`. Cheaper chain: `sonar-deep-research` → `sonar-pro` → `sonar`. Temp 0. On fail: `call_perplexity` prints; `call_perplexity2` returns **None**.

| Function | Default model | Notes |
|---|---|---|
| `call_perplexity` | sonar-deep-research, max 50k, timeout 360 | TIW sentiment |
| `call_perplexity2` | same, retries=3 | RFW, TAM, H2H, CJA, beta fallback |
| `get_competitor_metrics_for_valuation` | sonar-pro | CapIQ competitor processor |
| `fetch_company_web_data` (`web_search.py:64`) | **sonar-pro** raw HTTP | section jinja `templates/research/web_search_prompt_section{N}.jinja`; **raises** |

---

## OpenAI (`call_openai.py`) — `OPENAI_API_KEY`

| Function | Default | Notes |
|---|---|---|
| `call_openai` | gpt-4o-mini, temp 0.3, max 1000 | 3+1 cheaper, never below gpt-4 |
| `call_openai_o_series` | o3, effort high, max 16k | |
| `call_openai_deep_research` | gpt-4o; o1 if use_reasoning | temp 0.7, 2–3 attempts |
| `call_openai_web` | wraps deep_research gpt-4o | RFW OpenAI branch |
| `call_openai_dcf_streaming` :687 | **gpt-5.6-sol**, max 128k, effort medium, timeout 3600, **stream Responses API** | optional `[{"type":"web_search"}]`; cache key sha256 + 24h retention; fallback to chat.completions only if web_search=False |
| `companySummary.Summarize` | **gpt-4o**, temp 0.4, max 600 | workflow start |

---

## DeepSeek (`call_deepseek.py`)

```
DEEPSEEK_BASE_URL = "https://api.deepseek.com"   # HARDCODED — env ignored
_FLASH_MODEL = "deepseek-v4-flash"               # DEEPSEEK_MODEL env logged and ignored
```

Key: `DEEPSEEK_API_KEY` | `deep_seek_api_key` | `DEEP_SEEK_API_KEY`.

`_call_raw` :708: thinking on → `extra_body.thinking.enabled` + effort; off → temp 0. Max tokens clamp 384000. 3 retries [10,30,60]s. **Never streams.** Empty+thinking → bump tokens 1.5×.

| Function | Thinking | Max tokens | Notes |
|---|---|---|---|
| `call_deepseek` | off default | 8000 | RA Pass 1/3, link router |
| `call_deepseek_writing` | ON high | 128k | cheap writer |
| `call_deepseek_writing_web` | Responses API | env or 65536 | **`[{"type":"web_search"}]`**; timeout env or 360; if fail and `allow_offline_fallback` → writing (unless `force_web_search`) |
| `call_deepseek_thinking` | ON (xhigh→max) | 128k | replaces Claude thinking |
| `call_deepseek_query` | OFF temp 0 | 2000 cap 16k | |
| `call_deepseek_deterministic` | OFF temp 0 | 16k | |
| `call_deepseek_json` | OFF json_object | 32k | DCF STRUCTURED |
| `call_deepseek_extraction` | ON max | 64k | DCF EXTRACTION |
| `call_deepseek_summarize` | — | 600 temp 0.3 | replaces gpt-4o summary |
| `call_deepseek_batch` | sequential, not vendor batch | — | |

---

## DCF router (`dcf_llm.py` + `dcf_llm_registry.py`)

`DCF_LLM_PROVIDER` default **`openai`**. Valid: claude / openai / grok / deepseek.

| Role | OpenAI | Claude | Grok | DeepSeek |
|---|---|---|---|---|
| CODEGEN | gpt-5.6-sol | claude-fable-5 | grok-4.3 | flash |
| BS_BALANCE_GATE | gpt-5.6-sol | **claude-opus-4-8** | grok-4.3 | flash |
| CODE_FIX / SANITY / CONSTRAINTS / DOC | gpt-5.6-sol | opus-4-6 | grok-4.3 | flash |
| STRUCTURED / EXTRACTION / WRITING | gpt-5.6-terra | sonnet-4-6 | grok-4.3 | flash |

`call_dcf_llm_with_retry`: **4** attempts, delays [30,60,120]s, **no cheaper-model**. `enable_web_search` honored only on OpenAI path.

Cheap workflow wraps this so **STRUCTURED + EXTRACTION only** go DeepSeek. CODEGEN stays cloud provider.

---

## Cheap monkey-patch (`workflow_deepseek.py`) — every assignment

Patched: `call_claude` writing/writing_web/thinking/streaming_with_thinking/sonnet_query/deterministic/call_claude/haiku/sonnet_batch/warm_batch_cache; `call_gemini` / web / structured; `call_perplexity` / 2 / markdown / get_competitors; `call_openai` / web / deep_research; `companySummary.Summarize`; `web_search.fetch_company_web_data`.

**Not patched:** `call_gemini_file_api`, `call_gemini_deep`, `call_openai_dcf_streaming`, RAG retrievers.

Also re-patches locals in rfw_steps, rfw_synthesis, agentic_query_generator, repetition_steps, tiw_steps, cja_steps. Sets `AGENTIC_QUERY_MODEL = "deepseek-v4-flash"`. Stubs `call_grok_dcf_streaming` → `""`.

---

## Section routing (`workflow.py` `generate_section_content`)

Prefetch: Perplexity sonar-pro for sections **2–8 only**. CIO lens: 3× `call_claude_sonnet_query` before loop.

| Section | Writer | Web prefetch | Extra engine |
|---|---|---|---|
| 1 | `call_claude_writing` | no | red-flag digest + valuation extract |
| 2 | `call_claude_writing_web` | yes | then CJA 2.5 (Gemini structured + Perplexity + Claude writing); CJA fail → base only |
| 3 | `call_claude_writing_web` | yes | |
| 4 | **`call_claude_writing`** (no native web on writer) | yes | competitor list from CapIQ / competitors_workflow |
| 5 | TAM: Claude writing → Perplexity deep-research → Claude + writing compression | yes | Step 2 fail → continue; Step 3 fail → return step 1 |
| 6,7 | `call_claude_writing_web` | yes | |
| 8 | UE DCF (`call_dcf_llm*`) then Claude writing exec; 8.5 `call_claude_writing_web` | yes | beta first (Gemini interactions, Perplexity fallback). **DCF raise aborts S8** |
| 9 | `call_claude_writing_web` | **no prefetch** | cashflow + capital structure: Opus thinking 10k/8k, Excel as 1h cache |
| 10 | TIW: Perplexity sentiment + Claude writing | — | |
| 11 | ACS: 3× Claude writing, full-report cache | — | fail → stub appendix |
| 12 | background RFW | — | default llm_list = **["Perplexity"]** only |

---

## Engine mismatches (comments vs code)

1. RA Pass 1/3 + link router: logs/env say Sonnet; **code is `call_deepseek`**. `RISK_AUDITOR_SONNET_MODEL` is **not passed**.
2. RFW synthesis docstring says Gemini; code is `call_claude_deterministic`.
3. Chatbot `determine-action`: **Opus 4.6**, temp 0, 10-token router. Fail → `action=query`.
4. Chatbot **stream** has no Gemini fallback; sync `generate_with_fallback_chatbot` does.
5. Brain skills distillation uses `ANTHROPIC_API_KEY` / `PI_ANTHROPIC_API_KEY`, **not PI_DD**.
6. Bypass wrappers (no unified retry): `categorize_pdfs.py` Haiku, `processPDF` Gemini 2.5-pro, `valuation_extractor.py` Haiku, `competitor_enrichment.py` Opus, `search_excels.py` Sonnet PI_CHATBOT.

---

## Chatbot / n8n

| Path | Model | Fallback |
|---|---|---|
| `/chatbot/determine-action` | Opus 4.6 | action=query |
| `/chatbot/query-report` | Sonnet PI_CHATBOT → Gemini 2.5-pro | error dict |
| `/chatbot/stream-query` | Sonnet only | SSE error |
| agentic_query | planner+synth Sonnet chatbot; web `call_claude_web_chatbot` | default plan web+report |
| search-pdfs | Gemini File RAG | error |
| search-excels | Sonnet PI_CHATBOT direct | error string |

---

## Prompt roots

`templates/sections/`, `templates/research/`, `templates/retrieval/`, `templates/valuation/`, `src/engines/*/prompts` or `*_prompts/`, `src/brain/prompts/`, `src/n8n_helpers/prompts/`, `src/services/Company_Review/prompts/`.
