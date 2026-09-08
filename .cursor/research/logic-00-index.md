# LLM logic — second pass (index)

Recorded 2026-09-08. This is the line-level logic catalog. The first-pass map is `llm-audit.md`.

| File | Contents |
|---|---|
| `logic-01-phoenician-intelligence.md` | Every PI wrapper, retry, monkey-patch, section route, engine |
| `logic-02-portfolio.md` | Portfolio Claude/DeepSeek clients, stages, debate, earnings battery |
| `logic-03-screening-capiq-earnings.md` | Screening factory, CapIQ screen providers, Earnings_tracker |
| `logic-04-router-and-light.md` | ai-router tool loop, Linker, investor-portal, dcf--app, C# TTS/admin, confirmed no-LLM |
| `logic-05-third-pass-usage.md` | Per-repo usage: purpose, data flow, fail policy, missed surfaces |
| `logic-06-external-apis.md` | SerpAPI, Tavily, vendor web tools, FMP, CapIQ, AlphaSense, yfinance |
| `engine-bible.md` | **Build spec** for the local internet engine (contracts, hooks, fail rules) |
| `engine-surgical.md` | Fetch ladder, SerpAPI extras, WAF, JS IR, budgets, deny lists |

## Cross-cutting laws

1. **Almost nothing talks to ai-router.** Apps call cloud SDKs. `DEEPSEEK_BASE_URL` is the intended hook and is still hardcoded to `https://api.deepseek.com` in PI (`call_deepseek.py:72`).
2. **Local Brain = Flash only.** Pro calls (Earnings `deepseek-v4-pro`, some PI paths) will 404 on a Flash-only vLLM.
3. **Web search is vendor-native.** Claude `web_search_20250305`, Gemini `GoogleSearch()`, Perplexity Sonar, DeepSeek cloud `/responses` `web_search`, SerpAPI, Tavily, Z.ai. Local Flash has none of these unless this repo (or ai-router tools) provides them.
4. **Cheap PI path is a monkey-patch**, not a second codebase. DCF streaming and Gemini File RAG are **not** patched.
5. **Fail policies differ.** Screening memo/analyst fail-open to templates. PI Section 8 DCF fail-closed (raises). Router search fail-open (“answer from knowledge”). Linker fail-soft per ticker.
6. **Embeddings are cloud-only.** Screening-engine OpenAI `text-embedding-3-small`. PI local E5 embeddings were removed.
7. **Broken screening call sites:** `get_llm_client(model).complete(...)` in transcript analyzer, 8-K scanner, feedback analyzer — factory returns a raw SDK client with no `.complete()`.

## First callers for a local search layer

1. PI `call_deepseek_writing_web` + `fetch_company_web_data` (Perplexity prefetch)
2. Portfolio DeepSeek universe (search currently **dropped**)
3. Earnings SerpAPI + DeepSeek extract
4. Screening `complete_with_search`
5. CapIQ `phoenician_tools` / screening web search
