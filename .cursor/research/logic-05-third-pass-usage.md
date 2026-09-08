# Third pass — usage analysis of every repo

Recorded 2026-09-08. This pass is about **how** each product uses an LLM (purpose, data in/out, fail behavior), plus surfaces the first two catalogs only named.

Call-level tables remain in `logic-01` … `logic-04`. Index: `logic-00-index.md`.

`pi-global` `pipelines.js` is a curated map of the code. It is mostly right. Gaps vs live code are called out below.

---

## 1. `phoenician-intelligence` — the DD engine

**Job:** Turn a ticker into a 12-section institutional report + DCF Excel, then keep it interrogable via chatbot.

**How LLM is used (stages, not wrappers):**

1. **Describe** — OpenAI `gpt-4o` writes a short company blurb reused in every section. Hardcoded. Not switchable.
2. **Remember** — Claude Sonnet turns investor-memory DB hits into CIO questions. Fail silent.
3. **Index** — Gemini File Search / Vertex / AlphaSense. Not generation.
4. **Ask** — Sonnet generates + scores retrieval queries per section.
5. **Prefetch web** — Perplexity `sonar-pro` for sections 2–8 only (`fetch_company_web_data`).
6. **Write** — Sonnet writing or writing+Anthropic web, section-dependent. Writing fallback → Gemini 2.5-pro. Writing-web fallback → Haiku.
7. **Specialize** — engines (DCF, CJA, TAM, TIW, ACS, RFW, cashflow, beta, H2H, RA) each pick their own model.
8. **Chat** — Opus classifies intent (10 tokens). Q&A Sonnet + Gemini fallback. Stream = Sonnet only.

**Newly recorded this pass**

| Surface | Usage | Fail |
|---|---|---|
| `industry_capacity.py` | Direct Perplexity `sonar-pro` (bypasses wrapper) only if capacity-driven industry. ≤350 words + citations. | Empty text; writer must say “not disclosed” |
| `ipo_date_fetcher.py` | Perplexity sonar-pro, retries=2, timeout 30. Regex parse date/exchange/price. | Cache `ipo_date_not_found`; no re-fetch |
| `company_pdf_downloads/perplexity.py` | **Filename lie.** Production is Claude Sonnet **web** (`call_claude_web`, PI_DD). Legacy Perplexity IR URL unused by `main_selenium`. | No PI_DD → RuntimeError |
| `prefetch_pipeline.py` `claude_find_website` | Last resort after FMP + Google CSE. Sonnet web. | URL regex + domain blocklist |
| Lab `run.py` | Replay section writers. `PI_LAB` temporarily **masks PI_DD**. DeepSeek if fixture fn contains “deepseek”. | Cost meter null on DeepSeek |
| Lab `improve-prompt` | Haiku meta-prompt (PI_DD) | — |
| `short_dcf_main.py` | Full DCF role registry + mechanical syntax fix + echo guard + beta regex overwrite | Cache skip if files exist |
| Skills distillation | **Different key:** `ANTHROPIC_API_KEY` / `PI_ANTHROPIC_API_KEY`. Sonnet temp 0, max 512. | API fail → do not stamp (retry later) |
| Brain mine | Sonnet deterministic, PI_DD, gated by `BRAIN_USE_LLM` | Raises if disabled |
| Chatbot temps | query 0.3 / 4000; suggest+modify **0.7** / 8000; determine-action **0** / 10 / Opus |
| `search_excels` | Direct Anthropic Sonnet PI_CHATBOT, full Excel dump | error string |
| `ir_email_lookup.py` | **No LLM** — SerpAPI only |
| `nolinks.py` | **No LLM** |

**Cheap path usage:** Same workflow, Flash shims. `fetch_company_web_data` shim calls `call_deepseek_writing_web` **without** forcing web unless DeepSeek defaults do. DCF CODEGEN stays cloud. Gemini File RAG stays cloud. `industry_capacity` still hits real Perplexity.

**pi-global vs code:** `pipelines.js` says Red Flags is a 4-provider fan-out. Live default `llm_list = ["Perplexity"]` only. DCF documented as GPT-5.5; code registry is `gpt-5.6-sol` / `gpt-5.6-terra`.

**Local search impact:** Almost every writer that uses `*_web` or Perplexity prefetch will go blind. Capacity, IPO date, PDF IR discovery, and section prefetch are all live-web dependent.

---

## 2. `phoenician-intelligence-backend`

**Job:** Orchestrate requests, persist reports, bill tokens, proxy TTS, admin log analysis.

**LLM usage:** None for reports. Three admin Claude calls (Haiku errors, Sonnet logs). TTS is OpenAI speech passthrough. Cost services are accounting.

**Local search impact:** None. Keep pointing at Python.

---

## 3. `phoenician-intelligence-frontend`

**Job:** Render reports, chat UI, TTS.

**LLM usage:** Zero in the browser. Chat → n8n + Python `/chatbot/*`. TTS → `gpt-4o-mini-tts`. Lab types only display backend metadata.

**Local search impact:** None.

---

## 4. `ai-router`

**Job:** Least-loaded proxy to local vLLM Flash Brains.

**LLM usage:** Does not think. Forwards OpenAI chat-completions. Optional `phoenician_tools.web_search` = SerpAPI ∥ Tavily snippets, 3 rounds, no fetch.

**Usage pattern apps must copy:** Change `base_url` only. Opt into tools or they get a dumb Brain.

**Local search impact:** This is the insertion point. Search quality today is the gap.

---

## 5. `phoenician-portfolio`

**Job:** Build / serve an AI investment book (weights, risk, debate, lessons) and run earnings predict.

**How LLM is used:**

- **Book construction** is a 6-stage structured-JSON pipeline. Claude by default (Sonnet company → Opus synthesis → Fable review → Opus risk). Optional DeepSeek universe **pins every stage to Flash xhigh and deletes tools**.
- **Debate** is the only book path that can search the web (Anthropic tool, max 5). Router pass is no-thinking heuristic-fallback.
- **Lessons** are 6 structured calls, no web. Independent of `ENABLE_LLM_STRATEGY` if `ENABLE_LESSONS` is on.
- **Trader pace** is structured JSON with deterministic fallback. Narrative is optional prose and must not change numbers.
- **Custom research** is Stages 1+2+6 on a Claude-only client.

**Earnings predictor (same repo):**

- Calendar date: DeepSeek `deepseek-chat` + SerpAPI.
- Judge: Sonnet only (Opus rejected), non-streaming.
- Insiders: Opus chunked JSON.
- `forecast/pipeline.py`: Claude battery errors are **caught**; pipeline continues empty.
- `calibration/freeze.py`: **No LLM.** Snapshots prior `p_beat` / `llm_crux`.

**Default off:** `ENABLE_LLM_STRATEGY=false` still serves the last cached book + live prices.

**Local search impact:** DeepSeek universe is already blind. Debate will lose web unless we replace `web_search_20250305`. EP calendar extract still needs SerpAPI or equivalent.

---

## 6. `capiq-screen-agent`

**Job:** Screen ~16k names, PM chat, playbooks, Dreams, auditor gates. Chrome extension is a thin client.

**How LLM is used (the real loop):**

```
row → quotes/ownership (code)
    → Haiku/GLM archetype
    → PHASE 1 research brief (web ON, never from cache)
    → optional DeepSeek gate walkthrough (advisory, never throws)
    → PHASE 2 verdict JSON (web OFF if brief exists)
    → unit-economics code may uplift verdict
```

Historical screens skip research+web.

**Desks:** Anthropic / GLM+Z.ai search / DeepSeek (no native web on OpenAI path — worker falls back to Anthropic if `webSearch`) / OpenRouter web plugin.

**Chat:** Memory opener → short sparring (1 search unless prefetch) → finish extracts Pass/Watch (fail → null, finish continues).

**Dreams:** Nightly Managed Agents consolidation. GLM desks skip. Refresh chain continues if a stage dies.

**Auditor:** Identify + evaluate with web (6 uses). Soft-fail — never blocks the screen. Budget 20 evals/batch. Branded firms skip LLM.

**Playbooks / events / NE:** Synthesis + Haiku classify; events extract after chat; NE reads Phase 1 brief, does not overwrite `current_verdict`.

**Compare judges:** Admin-only OpenAI `gpt-4o-mini` A/B. Not production screening.

**Local search impact:** Phase 1 research is the critical replacement. DeepSeek desk cannot search today. Auditor identify needs web or it nulls the gate.

---

## 7. `screening-engine`

**Job:** Ingest universe, score, write memos, RAG.

**How LLM is used:**

- **Judge with web:** analyst agent (4 searches), memo (2), universe expand, IR monitor, intl discovery (25 searches).
- **Ingest without web:** Perplexity `sonar-deep-research` news + transcripts (`ingestion_worker` news step only).
- **Extract:** OpenAI `gpt-4.1-mini` financials/claims.
- **Gate:** Haiku business-model — **fail-open pass=True**.
- **RAG:** OpenAI embeddings → pgvector. Separate RAG memo uses `complete()` not search.

**Fail-open culture:** memo → template; analyst → Python scores; news error → that step fails, others commit.

**Broken:** `get_llm_client().complete()` in transcript analyzer, 8-K scanner, feedback analyzer.

**Local search impact:** Replace `complete_with_search`. News/transcripts need a Perplexity equivalent. Embeddings stay a separate problem (not this repo’s search job unless we add a local embedder).

---

## 8. `Earnings_tracker`

**Job:** Find earnings events, docs, webcasts, news. Summarize for PMs.

**How LLM is used — SerpAPI finds, LLM judges:**

`ranker.py` 8 DeepSeek calls (all `deepseek-chat`, temp 0.1):

1. pick best document  
2. classify page links  
3. verify IR domain  
4. find calendar URL  
5. find webcast  
6. hop to event row  
7. aggregator transcript fallback  
8. verify event match  

Then `extract.py` writes the IC summary JSON from the verified doc (or snippets with a confidence penalty).

Finders for calendar/webcast/reports default **`deepseek-v4-pro`**. News: SerpAPI L1, Gemini+Google Search L2 (2 passes), DeepSeek classify, Gemini second opinion if confidence < 0.6.

**Fail:** Ranker returns None and tries the next candidate. Extract exception → no legacy fallback. News timeout 120s skips company.

**pi-global gap:** Map says “all DeepSeek.” Live news layer is Gemini+Search.

**Local search impact:** Flash-only Brain breaks Pro finders. Ranker JSON contracts must be preserved. Gemini news grounding must be replaced.

---

## 9. `Linker`

**Job:** CapIQ capital-allocation math. Optional Claude qualitative 0–40 business-quality score, cached CSV. 8 workers, 3 retries. Fail-soft per ticker.

**Local search impact:** None (no web). Local Flash can replace Sonnet if we keep the JSON `{score, rationale}` contract.

---

## 10. `investor-portal-backend`

**Job:** Investor documents. LLM is **admin extraction only** — names, statement segments, contract notes, subscription dates, annual-report years. `gpt-4o-mini`, vision `gpt-4o`, temp 0. Fail-closed on rename script (low confidence / UNKNOWN → no rename).

**Local search impact:** None.

---

## 11. `dcf--app`

**Job:** Browser DCF toy. Gemini 3 flash + Google Search, JSON schema, thinking off. Key in the Vite bundle. Fail → null.

**Local search impact:** Entire app is a cloud Gemini call from the client.

---

## 12. `dcf-app`

Empty clone. No usage.

---

## 13. `pi-global`

**Job:** Internal map of the company’s infrastructure. **Documents** LLM usage; does not call models.

Treat `pipelines.js` / `intelligence.js` as the intended story. Trust the code when they disagree (RFW providers, Earnings Gemini, DCF model ids).

---

## 14. `phoenician-frontend-kit`

Svelte kit + **sample** Claude cost rows. Live mode calls portfolio/screen backends. No inference here.

---

## 15–21. No production LLM

| Repo | What it does |
|---|---|
| `phoenician-mail-sender` | Graph mail |
| `Factsheet-Automation` | Performance math |
| `phoenician-capital-website` | Marketing site |
| `investor-portal-web` | Investor UI |
| `investor-portal-mobile` | Investor app |
| `investor-portal-backend-archive` | Old backend |

---

## Key isolation (company-wide)

| Key | Who bills it |
|---|---|
| `PI_DD` | DD writers, PDF Claude discovery, brain mine, lab improve-prompt |
| `PI_CHATBOT` | Chatbot + Excel search + async Claude |
| `PI_LAB` | Lab replay (masks PI_DD) |
| `ANTHROPIC_API_KEY` / `PI_ANTHROPIC_API_KEY` | Skills distillation; portfolio; Linker; screen; C# admin |
| `DEEPSEEK_API_KEY` | Cheap PI, portfolio universe, screen desk, Earnings, RA 1/3 |
| `PERPLEXITY_API_KEY` | PI prefetch, capacity, IPO, RFW, screening news |
| `GEMINI_API_KEY` | PI RAG + CJA + beta; Earnings news; dcf--app |
| `OPENAI_API_KEY` | PI summary + DCF; screening embeddings; portal PDFs; TTS; screen judges |
| `SERPAPI_KEY` | Earnings, PI scrapers/IR, ai-router, portfolio calendar |
| `TAVILY_API_KEY` | ai-router only |
| `XAI_API_KEY` | PI Grok DCF (optional, unused in most src) |
| `ZAI_API_KEY` / `OPENROUTER_API_KEY` | CapIQ desks |
| `ROUTER_API_KEY` | ai-router callers |
| `phoenician-ai-api-keys` | AWS blob: OpenAI + DeepSeek + SerpAPI |

---

## Fail-policy by product (how a local search layer must behave)

| Product | If search/LLM dies |
|---|---|
| PI DCF / cashflow / ACS | Raise or stub section — do not invent numbers |
| PI capacity / IPO | Empty + “not disclosed” / cached miss — do not invent % |
| PI chatbot intent | Default `query` |
| PI chatbot stream | Error event |
| Portfolio debate router | Keyword plan |
| Portfolio EP Claude battery | Empty judge, continue |
| CapIQ Phase 1 research | Phase 2 searches inline |
| CapIQ Phase 2 verdict | **Throw** — row fails |
| CapIQ auditor | Null gate, screen continues |
| Screening memo/analyst | Template / Python |
| Earnings ranker | Next candidate |
| Earnings extract | Null summary |
| ai-router search | **Wrong for us:** “answer from knowledge” |
| Linker / portal rename | Skip that file |

---

## What a perfect local search layer must replace (priority)

1. Anthropic `web_search_20250305` (PI writers, screening, CapIQ chat/screen/auditor, portfolio debate)
2. Perplexity Sonar (PI prefetch/RFW/TAM/IPO/capacity, screening news/transcripts)
3. Gemini Google Search (PI CJA/competitors/beta, Earnings news, dcf--app)
4. DeepSeek cloud `/responses` web (PI cheap writing_web)
5. SerpAPI judgment loop (Earnings ranker + calendar)
6. Z.ai / OpenRouter web (CapIQ desks)
7. Tavily (ai-router only — already weak)

Page fetch + extract is required. Snippets are not enough for DD, screen research briefs, or earnings document verify.
