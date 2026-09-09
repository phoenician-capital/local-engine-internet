# local-engine-internet

Search and fetch on `:8090`. Does not run the LLM.

**Read [docs/method.html](docs/method.html)** — how it works and what is in the repo.

```bash
cp .env.example .env    # set SERPAPI_KEY
python -m engine        # http://127.0.0.1:8090
```

- Toggle: http://127.0.0.1:8090/ui
- OpenAPI: http://127.0.0.1:8090/docs
- Chat: `http://127.0.0.1:8090/v1` (OpenAI-compatible)
- Search: `POST /v1/search`

```bash
pytest
python scripts/check_search.py
```
