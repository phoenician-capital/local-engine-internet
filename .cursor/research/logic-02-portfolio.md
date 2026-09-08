# Portfolio + earnings battery — every LLM logic bit

Paths under `org-repos/phoenician-portfolio/`.

---

## Two clients (`engine/core.py`)

| | AnthropicClient (`strategy/claude.py`) | DeepSeekClient (`strategy/deepseek.py`) |
|---|---|---|
| Transport | `messages.stream` always | `chat.completions.create(stream=True)` |
| Model | per-call arg | **pinned** `deepseek-v4-flash` — caller model ignored |
| Effort | adaptive thinking + `output_config.effort` | `thinking.enabled` + `reasoning_effort`; pinned **xhigh** |
| Web search | if caller passes `tools=` (attempt 0 only; repair strips tools) | **`del tools`** — never |
| Fallback model | yes (`CLAUDE_FALLBACK_MODEL` default opus-5) | **no** |
| JSON | brace-extract + 2 repair prompts | `json_object` + same extract; max 32k JSON / 128k text |
| Transient retries | 4 + backoff; Fable `refusal` → jump to fallback | 4 only |
| Base URL | api.anthropic.com | `DEEPSEEK_BASE_URL` or `https://api.deepseek.com` |

Empty `effort=""` → no thinking (Debate router).

---

## Flags (`strategy/config.py`)

`ENABLE_LLM_STRATEGY` default **off**. If on and no `ANTHROPIC_API_KEY` / `ANTHROPIC_SECRET_ARN` → `ConfigError`.

When **off**: price loop still serves cached book. Universe / custom research clients are None.

When off but `ENABLE_LESSONS=1` + key: `_lessons_client` and `_debate_client` still exist.

---

## Claude tier env

| Tier | Model env | Default | Effort env | Default |
|---|---|---|---|---|
| Company / red-team | `CLAUDE_MODEL` | claude-sonnet-5 | `CLAUDE_EFFORT` | medium |
| Synthesis / refine | `CLAUDE_SYNTHESIS_MODEL` | claude-opus-5 | `CLAUDE_SYNTHESIS_EFFORT` | high |
| Review | `CLAUDE_REVIEW_MODEL` | claude-fable-5 | `CLAUDE_REVIEW_EFFORT` | max |
| Stage 0 batch | uses model | — | `CLAUDE_STAGE0_EFFORT` | xhigh |
| Risk model | `CLAUDE_RISK_MODEL` | claude-opus-5 | `CLAUDE_RISK_MODEL_EFFORT` | max |
| Portfolio risk chips | `CLAUDE_PORTFOLIO_RISK_MODEL` | claude-sonnet-5 | `CLAUDE_PORTFOLIO_RISK_EFFORT` | xhigh |
| Lessons | `CLAUDE_LESSONS_MODEL` | claude-sonnet-5 | `CLAUDE_LESSONS_EFFORT` | xhigh |
| Debate | `CLAUDE_DEBATE_MODEL` | claude-sonnet-5 | runtime | — |
| Fallback | `CLAUDE_FALLBACK_MODEL` | claude-opus-5 | — | — |

Also: timeout 1200s, max retries 4, `STAGE0_BATCH_SIZE=5`, `SYNTHESIS_SAMPLES=3`, `REFINE_MAX_ITERS=2`, `ENABLE_RED_TEAM` true.

---

## DeepSeek universe switch (`providers.py` + `lifecycle.py`)

Only exact `"deepseek"` is DeepSeek; else Claude. `pin_deepseek_universe_config` rewrites **all** model+effort fields to Flash + xhigh, including `fallback_model`.

**Not pinned:** `portfolio_risk_model` — chip pass stays Claude on `_custom_research_client`.

What is dropped vs Claude universe: per-tier models, mixed efforts, cross-model fallback, adaptive thinking, Fable refusal path, citation sink. Prompts/schemas unchanged.

---

## Pipeline (all `client.structured`, no tools)

| Stage | File | Model / effort | Extra logic |
|---|---|---|---|
| 0 batch | `stage0.py` ~210 | model + stage0_effort | bisect batch on failure |
| 0 consolidate | ~319 | synthesis_model + synthesis_effort | |
| 1 company | `company.py` ~92 | model + effort | 1 extra serial retry per ticker; content-hash cache |
| 2 red-team | `stages.py` ~82 | same | skip if `red_team` false; same serial retry |
| 3 synthesis | `scoring.py` | synthesis tier | best-of-N parallel (`synthesis_samples`) |
| 4 refine | same | synthesis tier | up to `refine_max_iters` |
| 5 review | `stages.py` ~235 | review tier | fail-closed completeness; Fable refusal → fallback |
| 6 risk | `risk.py` ~64 | risk_model tier | **swallowed**; book unaffected |
| Portfolio chips | `risk.py` ~140 | portfolio_risk tier | custom research + lab save; Claude only |

Custom research (`custom_research.py`) needs `ENABLE_LLM_STRATEGY`. Stages 1+2+6. No web search.

---

## Debate

Pass 1 router (`debate/router.py` ~137): `debate_model`, **effort=""**, no tools. Fail → keyword `_heuristic_plan`.

Pass 2 answer (`debate/service.py` ~90):
- thinking FE toggle → effort `"medium"` or `""` (config comment wrongly says `"low"`)
- `web_search=True` → attach `web_search_20250305` max_uses **5** (`catalog.py` ~165)
- parse fail + web → retry **once without tools**; still fail → 502
- no client → static JSON explaining plan

Needs `_debate_client` (strategy **or** lessons + key).

---

## Lessons (`strategy/reflect/runner.py`)

5 layer structured calls + 1 consolidate. `lessons_model` + `lessons_effort`. No tools. Skip LLM if no material divergences. Needs `ENABLE_LESSONS`.

`forecast_grade/llm.py` — **no LLM**. Trims packets for lessons prompts only.

---

## Technical trader

**Pace** (`pace.py` ~230): structured, default model sonnet-5, effort **xhigh**. `technical_trader_pace_effort` is **not on EngineConfig** — always xhigh. Fail → deterministic `fallback_participation()`. Client = `_client` or `_lessons_client`.

**Narrative** (`narrative.py` ~119): `client.text` effort low if wrapper; else raw **`messages.create` non-streaming, max 900, no thinking, no retry**. Never changes plan numbers.

---

## Earnings predictor (same monorepo)

**Key inject** (`earnings_bridge.py`): Anthropic from engine secret; SerpAPI + DeepSeek key/url/model from `phoenician-ai-api-keys`.

**Claude battery** (`earnings_predictor/llm_battery/claude_runtime.py`):
- Judge: `CLAUDE_EARNINGS_MODEL` or synthesis model; **Opus rejected**. Effort default high. `messages.create` **non-stream**, adaptive thinking, max 16384. Budget `EP_CLAUDE_MAX_CALLS` default 55. Disk cache skips budget. No web search.
- Insider: `CLAUDE_INSIDER_MODEL` default opus-5, effort high. `insider_llm.py` chunks ~4 tickers/call via `complete_json`.

**Calendar** (`calendar/smart_finder.py`):
- Model `DEEPSEEK_MODEL` default **`deepseek-chat`** (not Flash)
- OpenAI-compatible, temp 0.1, `json_object`, max 3072, **non-stream**, no thinking
- SerpAPI then DeepSeek extract

---

## ENABLE_LLM_STRATEGY off matrix

| Feature | Works? |
|---|---|
| Cached book + live prices | yes |
| Universe / AI pipeline | no |
| Custom research | no |
| Debate | only if ENABLE_LESSONS + key |
| Lessons | only if ENABLE_LESSONS + key |
| Trader Claude pace | if lessons client; else heuristic |
| DeepSeek universe | no (needs universe run) |
| Earnings predict | independent (own env inject) |
