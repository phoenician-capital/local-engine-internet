# Phoenician Capital — LLM usage audit

Audited every repo under `org-repos/` on 2026-09-08. Source of truth for building `local-engine-internet`.

Clones: `org-repos/<repo>`. This file is research, not a rule.

---

## 1. The actual problem

The company is moving inference to **local DeepSeek Brains** behind `ai-router`. Local vLLM serves `deepseek-v4-flash` only. Cloud models that search the web today:

- Anthropic `web_search_20250305`
- Perplexity Sonar
- Gemini Google Search
- DeepSeek cloud `web_search`
- SerpAPI / Tavily / Z.ai

None of those exist on a local Brain. `ai-router` already has a thin snippet search. It is not wired into production apps and it does not fetch pages.

---

## 2. Repo by repo

### 2.1 `ai-router` — local inference proxy (the existing piece)

**Role:** FastAPI OpenAI-compatible proxy to on-prem vLLM. Local only. No cloud LLM fallback.

**Key files**

| Path | Role |
|---|---|
| `app/main.py` | `POST /chat/completions` and `/v1/chat/completions` |
| `app/backends.py` | Least-loaded Brain pick; 503 if none |
| `app/proxy.py` | Forward; 502 on Brain failure, no retry |
| `app/tools/orchestrator.py` | `phoenician_tools` loop, `MAX_TOOL_ROUNDS = 3` |
| `app/tools/web_search.py` | SerpAPI + Tavily snippets |
| `app/streaming.py` | SSE passthrough; cannot combine with tools |
| `app/config.py` | `BRAIN_n_*`, `ROUTER_API_KEY`, `SERPAPI_KEY`, `TAVILY_API_KEY` |

**Models:** whatever the Brain serves. Docs: `deepseek-v4-flash`. Router does not rewrite `model`. Pro is not local.

**Search:** opt-in `"phoenician_tools": ["web_search"]`. Parallel SerpAPI + Tavily. Title/snippet/link. 5 results/provider. No fetch, no rank, no dedup. On failure: “answer from your own knowledge”.

**Intended first caller:** `phoenician-intelligence` via `DEEPSEEK_BASE_URL=http://<router>:8080`. **Not wired.** `call_deepseek.py` hardcodes `https://api.deepseek.com`.

**Auth:** `ROUTER_API_KEY` (unset = open). Admin: `ADMIN_API_KEY`. No tenants.

---

### 2.2 `phoenician-intelligence` — primary AI engine

All report generation lives here. C# backend and React frontend do not write reports.

**Client hub:** `src/services/llm_clients/`

| Module | Models / keys | Purpose |
|---|---|---|
| `call_claude.py` | Sonnet 4.6, Opus 4.6, Haiku 4.5; `PI_DD` / `PI_CHATBOT` | Writing, thinking, web tool, chatbot |
| `call_gemini.py` | 2.5-pro, 2.5-flash-lite, 3.6-flash | Writing fallback, GoogleSearch, File Search RAG |
| `call_openai.py` | gpt-4o / o-series / `gpt-5.6-sol` DCF | Company blurb, DCF, deep research |
| `call_deepseek.py` | `deepseek-v4-flash` only | Cheap workflow + some engines |
| `call_perplexity.py` | sonar-deep-research → sonar-pro → sonar | Cited web research |
| `call_grok.py` | xAI | Optional DCF / X search |
| `companySummary.py` | gpt-4o | Ticker blurb at workflow start |

**Main DD** (`src/core/workflow.py`): 12 sections. Perplexity prefetch for sections 2–8. Section 1 = Claude writing. Most others = `call_claude_writing_web`. Section 8 DCF uses `DCF_LLM_PROVIDER` (default openai). Section 12 red flags in a background thread.

**Cheap path** (`src/core/workflow_deepseek.py`): monkey-patches Claude/Gemini/Perplexity/OpenAI wrappers to DeepSeek **before** importing workflow. RAG stays Vertex/Gemini. DCF is **not** patched.

**RAG:** Vertex AI Search (`phoenician-intelligence-rag-v3`), Gemini File Search, AlphaSense. Local E5 embeddings **removed**. Agentic queries: Claude Sonnet generates retrieval queries (`templates/retrieval/`).

**Engines that hit the web or an LLM**

| Engine | LLM | Web |
|---|---|---|
| Unit economics / DCF | OpenAI / Claude / Gemini / DeepSeek / Grok | OpenAI Responses web optional |
| Red flags | Perplexity / Gemini web / OpenAI web + Claude synthesis | Yes |
| Competitors | Gemini + Gemini web + Claude thinking | Yes |
| Customer journey | Gemini structured + Perplexity + Claude web | Yes |
| TAM commentary | Perplexity + Claude | Yes |
| Technicals | Perplexity + Claude | Yes |
| Analyst challenge | Claude writing + RAG | File RAG |
| H2H | Perplexity then **DeepSeek** chapters | Yes |
| Risk auditor | DeepSeek pass 1/3, Claude cached pass 2 | Link routing via DeepSeek |
| Chatbot / n8n | Opus router, Sonnet synth, Claude web | Yes |
| Brain playbooks | Claude deterministic miner | No |
| Reviews | Haiku sentiment; SerpAPI scrape | SerpAPI |

**Prompts:** `templates/sections/`, `templates/research/`, `templates/retrieval/`, engine `*_prompts/`.

**ai-router:** not imported. Cloud only.

---

### 2.3 `phoenician-intelligence-backend` / `frontend`

| Surface | LLM? |
|---|---|
| `PythonReportService` | HTTP to Python only |
| `TextToSpeechController` | OpenAI TTS (`gpt-4o-mini-tts-2025-12-15`) |
| `DeveloperController` | Direct Anthropic for logs/errors |
| `LlmCostService` / vendor adapters | Cost sync (Anthropic, OpenAI, DeepSeek, GCP Gemini) |
| Frontend `ReportChatbot.tsx` | Proxies Python `/chatbot/*` + n8n |
| Frontend TTS | OpenAI only |

---

### 2.4 `phoenician-portfolio`

Server-side Claude book pipeline. Frontend only shows telemetry.

| Stage | Default model |
|---|---|
| Per-company | `claude-sonnet-5` |
| Synthesis / refine | `claude-opus-5` |
| Final review | `claude-fable-5` |
| Universe (optional) | `deepseek-v4-flash`, effort `xhigh` |

**Files:** `portfolio_manager/strategy/claude.py`, `deepseek.py`, `pipeline/*`, `debate/*`, `earnings_bridge.py`.

Web search: Anthropic tool in debate (`web_search_20250305`, max 5). DeepSeek universe path **strips / ignores** web search. Research dossiers come from PI API (`pi_client.py`), not local RAG.

Keys: `ENABLE_LLM_STRATEGY`, `ANTHROPIC_API_KEY` / `ANTHROPIC_SECRET_ARN`, `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`.

---

### 2.5 `capiq-screen-agent`

Chrome extension + Node backend. ~16k-name screener, PM chat, Managed Memory, nightly Dreams.

| Provider | Entry | Search |
|---|---|---|
| Anthropic | `backend/llm.js` `callClaude()` | `web_search_20250305` |
| DeepSeek | `backend/deepseek-screen.js` | via Anthropic-compatible URL |
| GLM / Z.ai | `backend/zai-web-search.js` | Z.ai web_search |
| OpenRouter Llama | `backend/openrouter-screen.js` | — |
| OpenAI | judge scripts | comparison only |

Other: `managed-agents.js`, `question-engine.js`, `cross-notes.js`, `skills-updater.js`, `anthropic-auditor-research.js`. Extension has no direct LLM calls.

---

### 2.6 `screening-engine`

Python screening factory. **Does not use ai-router.**

**Factory:** `src/shared/llm/client_factory.py` — `complete()`, `complete_with_search()` (Anthropic web tool), Perplexity OpenAI-compatible client.

**Embeddings:** `src/shared/llm/embeddings.py` — OpenAI `text-embedding-3-small` → pgvector (`src/rag/`).

**LLM call sites:** analyst agent, memo generator, BusinessModelAgent (Haiku), universe expander, market/news/transcript/IR ingest, financial parser, claims extractor, MCP embedder.

**Prompts:** `src/prompts/**/*.j2` (~38 templates).

Env: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `PERPLEXITY_API_KEY`, `PRIMARY_LLM`, `MEMO_LLM`, `EMBEDDING_MODEL`.

---

### 2.7 `Earnings_tracker`

DeepSeek OpenAI client (`https://api.deepseek.com`) + SerpAPI + Gemini Search.

| File | Role |
|---|---|
| `tracker/summary/ranker.py` | `LLMRanker` — many `chat.completions.create` |
| `tracker/summary/extract.py` | Summary + metrics |
| `tracker/smart_finder.py` | Calendar extraction |
| `tracker/webcast_finder.py` | Webcast URL extract |
| `tracker/news/classifier.py` | News class |
| `tracker/news/deep_research.py` | Gemini + Google Search |
| `tracker/earnings/extract_earnings.py` | SerpAPI extract |

Default model often `deepseek-v4-pro` / `deepseek-chat`. Local Flash-only Brain will break Pro calls.

---

### 2.8 Light / none

| Repo | LLM |
|---|---|
| `investor-portal-backend` | OpenAI gpt-4o-mini/4o on admin PDFs (`OpenAi*.cs`) |
| `Linker` | `capiq/analysis/qualitative.py` Claude Sonnet 4.6, cached CSV |
| `dcf--app` | `services/gemini.ts` Gemini 3 flash + Google Search, key in Vite bundle |
| `dcf-app` | Empty clone |
| `pi-global` | Docs/map only |
| `phoenician-frontend-kit` | UI + sample cost data |
| `phoenician-mail-sender` | No |
| `Factsheet-Automation` | No |
| `phoenician-capital-website` | No |
| `investor-portal-web` / `mobile` / `backend-archive` | No |

---

## 3. Provider inventory

| Provider | Used by | Typical models |
|---|---|---|
| Anthropic | PI, portfolio, screening, CapIQ screen, Linker, C# admin | Sonnet 4.6/5, Opus 4.6/5/4.7, Haiku 4.5, Fable 5 |
| DeepSeek cloud | PI cheap, portfolio universe, CapIQ screen, Earnings, risk auditor | v4-flash, v4-pro, deepseek-chat |
| DeepSeek local (vLLM) | ai-router Brains only | `deepseek-v4-flash` |
| OpenAI | PI DCF/summary, screening embeddings, investor-portal PDFs, TTS | gpt-4o, gpt-4o-mini, gpt-4.1-mini, embeddings-3-small, TTS |
| Gemini | PI RAG + web, Earnings news, dcf--app | 2.5-pro, 2.5-flash-lite, 3.x flash |
| Perplexity | PI research, screening ingest | sonar, sonar-pro, sonar-deep-research |
| xAI Grok | PI optional DCF | via `XAI_API_KEY` |
| Z.ai GLM | CapIQ screen desks | glm-5.2 |
| OpenRouter | CapIQ screen Llama path | llama-4-scout etc. |
| SerpAPI | Earnings, PI scrapers, ai-router | Google engine |
| Tavily | ai-router only | search API |

**Not used for inference:** LangChain/LangGraph (no real agents), LiteLLM, Ollama, Groq, local embeddings (removed from PI).

---

## 4. How a local LLM is supposed to attach today

```
App  --OpenAI chat completions-->  ai-router :8080
                                      |  pick least-loaded Brain
                                      |  optional phoenician_tools.web_search
                                      v
                                   vLLM Brain  (deepseek-v4-flash)
                                      |
                                   SerpAPI / Tavily   (snippets only)
```

Reality: every heavy app still hits cloud SDKs. `DEEPSEEK_BASE_URL` is the intended hook in PI, portfolio, Earnings, CapIQ screen — and it still points at `api.deepseek.com`.

---

## 5. What will break if we only swap the base URL

1. **Native vendor search disappears** — Claude/Gemini/Perplexity/DeepSeek-cloud tools never run on local vLLM.
2. **Pro vs Flash** — Earnings and some PI paths want `deepseek-v4-pro`. Local Brain is Flash.
3. **Embeddings** — screening-engine still needs OpenAI (or a local embedder) for pgvector.
4. **TTS** — frontend/backend stay on OpenAI; out of scope for search.
5. **RAG** — PI Vertex/Gemini File Search is cloud; not replaced by this repo.
6. **Opt-in** — router search is off unless `phoenician_tools` is set.
7. **Streaming + tools** — rejected by ai-router.
8. **Snippet quality** — DD/screening/earnings need page text, filings, citations — not 5 Google snippets.
9. **Hallucination fallback** — router currently tells the model to answer from memory when search is down.

---

## 6. Recommended split for this repo

| Layer | Owner |
|---|---|
| Local inference, load balance, auth | keep in `ai-router` |
| Search, fetch, extract, rank, cite | **this repo** |
| App prompts and workflows | stay in each product repo |

Highest-value first callers: PI cheap workflow + `call_deepseek.py`, then portfolio DeepSeek universe, then Earnings SerpAPI replacement, then screening `complete_with_search`, then CapIQ screen DeepSeek desk.

---

## 7. File index (start here when implementing)

```
org-repos/ai-router/app/tools/web_search.py
org-repos/ai-router/app/tools/orchestrator.py
org-repos/ai-router/app/main.py
org-repos/phoenician-intelligence/src/services/llm_clients/call_deepseek.py
org-repos/phoenician-intelligence/src/core/workflow_deepseek.py
org-repos/phoenician-intelligence/src/services/web_search.py
org-repos/phoenician-intelligence/src/services/llm_clients/call_claude.py
org-repos/phoenician-portfolio/portfolio_manager/src/portfolio_manager/strategy/deepseek.py
org-repos/screening-engine/src/shared/llm/client_factory.py
org-repos/capiq-screen-agent/backend/llm.js
org-repos/Earnings_tracker/tracker/summary/ranker.py
```
