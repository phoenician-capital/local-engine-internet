# Screening, CapIQ screen, Earnings_tracker — every LLM logic bit

---

## A) screening-engine

Factory `src/shared/llm/client_factory.py`:
- Route by substring: claude→Anthropic, gpt→OpenAI, gemini→Google, sonar→Perplexity, else OpenAI
- `complete()`: Anthropic **only** retried (4×, backoff 2s + jitter on 429/529/503/500/timeout). OpenAI/Google/Perplexity **no retry**
- `complete_with_search()`: Anthropic only, tool `web_search_20250305`, default `max_searches=5`
- `get_llm_client()` returns raw AsyncAnthropic/OpenAI — **has no `.complete()`**

Settings (`src/config/settings.py` 56–68):
`PRIMARY_LLM=claude-sonnet-4-6`, `MEMO_LLM=claude-opus-4-6`, `EXTRACTION_LLM=gpt-4.1-mini`, `PERPLEXITY_MODEL=sonar-deep-research`, `EMBEDDING_MODEL=text-embedding-3-small`

### complete_with_search

| File:line | Model | max_searches | Prompt | Fail |
|---|---|---|---|---|
| `memo_generator.py:142` | memo or primary | 2 | inline | `_template_memo()` |
| `analyst_agent.py:496` | primary | 4 | `scoring/analyst_*.j2` | `[]` → Python scoring |
| `universe_expander.py:96` | primary | 1 | `discovery/claude_universe_screen.j2` | second search extract :122 |
| `universe_expander.py:424` | **sonnet-4-6 hardcoded** | 2 | `discovery/similarity_search.j2` | `[]` |
| `universe_expander.py:439` | **sonnet-4-6 hardcoded** | 2 | `discovery/thematic_search.j2` | `[]` |
| `market_data/client.py:684` | primary | 3 | `ingestion/llm_financials.j2` | plain `complete()` :704 temp 0 → `{}` |
| `market_data/client.py:1169` | primary | **25** | `discovery/intl_candidate_discovery.j2` | `complete()` re-extract :1218 |
| `ir_monitor/client.py:79` | primary | 1 | inline JSON array | `[]`; **45s timeout** |

### complete (no search)

| File:line | Model | Prompt | Fail |
|---|---|---|---|
| `rag/generator/memo_generator.py:89` | memo_model | `memo/memo_*.j2` | none |
| `business_model_agent.py:104` | **haiku-4-5** | inline JSON | **pass=True** |
| `news/client.py:41,58` | **sonar-deep-research** | `ingestion/news_search.j2`, `web_read.j2` | none |
| `transcripts/client.py:35,63` | **sonar-deep-research** | fetch/list transcript j2 | none |
| `financial/parser.py:31` | extraction_model | `extraction/parse_financials.j2` | `{confidence:0}` |
| `claims/extractor.py:56` | extraction_model | `extraction/extract_claims.j2` | `[]` |
| `api/router.py:870` | **`"sonar"`** (not env default) | news_search j2 | per-holding except |

### Broken: get_llm_client().complete

`transcript_analyzer.py:108`, `eightk_scanner.py:109`, `selection_feedback_analyzer.py:196` (`model="claude-haiku"`). Factory returns raw SDK.

### Embeddings

`embed_single` / `embed_texts` → OpenAI. Used by `vector_retriever.py:35`, `chunker.py:48` (batch 100), MCP `embedder_tool.py:24`.

Rule-based agents (no LLM): Filter, Founder, Growth, RedFlag.

---

## B) capiq-screen-agent

### Provider precedence

| Layer | Env chain | Default |
|---|---|---|
| Chat/synth | `CHAT_LLM_PROVIDER` → `LLM_PROVIDER` → `SCREEN_LLM_PROVIDER` | anthropic |
| Screening | `SCREEN_LLM_PROVIDER` → `DD_LLM_PROVIDER` → `LLM_PROVIDER` | anthropic |
| Playbooks | `PLAYBOOK_LLM_PROVIDER` → screen → dd → LLM | |
| Events | `EVENTS_LLM_PROVIDER` → LLM → screen | |
| Future study | `NE_LLM_PROVIDER` → screen → dd → LLM | |

### Default models (`backend/llm.js` 64–79)

| | Anthropic | DeepSeek | GLM | OpenRouter |
|---|---|---|---|---|
| Chat | claude-sonnet-5 | deepseek-v4-flash | glm-5.2 | llama-4-scout |
| Synthesis | claude-sonnet-4-6 | same Flash | glm-5.2 | llama-4-scout |

`CLAUDE_MODEL` wins if set. `SCREEN_MODEL` overrides screen.

**Thinking:** adaptive + effort on Anthropic. **Stripped** for GLM/DeepSeek (`llm.js` 243–247, 328–332). Chat effort from `resolveChatThinking()` by investorTurns.

### Web search

| Path | Mechanism |
|---|---|
| Anthropic chat | `web_search_20250305` max_uses default 2 |
| Anthropic screen | same; `SCREEN_WEB_SEARCH` default ON; max_uses 60; per-name 15 |
| Phase 1 research | web ON |
| Phase 2 verdict | web **OFF** if research brief present |
| GLM | client tool loop → Z.ai `/paas/v4/web_search` |
| OpenRouter | plugin `{id:'web'}` |
| DeepSeek screen | **no web**; if `webSearch=true` worker uses Anthropic branch |

Concurrency `SCREEN_CONCURRENCY=5`. Per-name max tokens 8000.

### Managed Memory / Dreams

`managed-agents.js`: Memory stores (`managed-agents-2026-04-01`), Dreams (`dreaming-2026-04-21`), poll 90 min. Gated by `USE_MANAGED_MEMORY`. Dreams **skipped on GLM desks**. Orchestrator: synthesis → Dreams → playbooks.

### Key call sites

| File:line | What | Model | Web |
|---|---|---|---|
| `question-engine.js:75` | opener | MODEL_CHAT | max 2 if no prefetch |
| `question-engine.js:269` | chat reply | MODEL_CHAT | 0–1 by brief |
| `skills-updater.js:185` | distiller | MODEL_SYNTHESIS | no |
| `cross-notes.js:381` | compare | MODEL_SYNTHESIS | no |
| `screening-worker.js:831` | research | MODEL | research uses |
| `screening-worker.js:1057` | verdict | MODEL | conditional |
| `deepseek-screen.js:54` | create | Flash, `reasoning_effort:max` | no |
| `openrouter-screen.js:60` | create | OPENROUTER_MODEL | optional plugin |
| `anthropic-auditor-research.js:64` | identify+evaluate | sonnet-5 | **webSearchUses=6** |
| `server.js:2514` | stream chat | MODEL_CHAT | max 3 |
| `server.js:973` | research brief | MODEL_SYNTHESIS | max 2 |

Auditor: `AUDITOR_GATE_WEB_USES` default 6. Extension has **no** direct LLM.

---

## C) Earnings_tracker

All DeepSeek via `OpenAI(..., base_url="https://api.deepseek.com")`. Key often `OPENAI_API_KEY` used as DeepSeek key.

| Surface | Default model | Extra |
|---|---|---|
| Summary rank/extract | `deepseek-chat` | temp 0.1, JSON fence/brace parse |
| Ranker | same | **8** `chat.completions.create` (lines 169,278,373,429,517,603,700,847) |
| Extract | same | max 64k, `json_object` → None on fail |
| Smart finder / webcast / earnings extract | **`deepseek-v4-pro`** | SerpAPI first (3 retries exp backoff); extract max 8192 |
| Reports extract | v4-pro | 2 retries; `_extract_basic_summary` fallback |
| Report classify | DeepSeek json_object | rule fallback `_should_keep_report_fallback` |
| News classify | deepseek-chat temp 0.1 | rule fallback |
| News deep research | **`gemini-3.5-flash`** | Google Search if `ENABLE_GOOGLE_SEARCH`; retries + semaphore |

`summary_finder.py` orchestrates SerpAPI + ranker + extractor — no direct LLM.

Local Flash Brain **cannot** serve `deepseek-v4-pro` without a Pro Brain.
