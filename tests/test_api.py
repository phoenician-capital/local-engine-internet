from engine.config import settings


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "providers_configured" in body
    assert body["search_ready"] is False


def test_welcome_lists_try_curls(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["search_ready"] is False
    assert "/v1/search" in body["try"]["search"]
    assert "SERPAPI_KEY" in (body["hint"] or "")
    assert "check_search.py" in body["try"]["check"]
    assert body["connect"]["openai_base_url"].endswith("/v1")
    assert "openai_python" in body["connect"]["snippets"]


def test_openai_models_list(client):
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"]
    assert client.get("/models").status_code == 200
    assert client.get("/v1").json()["openai_base_url"].endswith("/v1")


def test_capabilities_lists_vllm_flags(client):
    resp = client.get("/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    flags = body["vllm_required_flags"]
    assert "--tool-call-parser deepseek_v4" in flags
    assert "--enable-auto-tool-choice" in flags
    assert body["search_ready"] is False


def test_stream_plus_tools_rejected(client):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "deepseek-v4-flash",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
            "phoenician_tools": ["web_search"],
        },
    )
    assert resp.status_code == 400
    assert "stream:true" in resp.json()["detail"]


def test_auth_required_when_key_set(client):
    settings.engine_api_key = "secret"
    resp = client.post("/v1/search", json={"query": "x"})
    assert resp.status_code == 401
    resp = client.post(
        "/v1/search",
        json={"query": "x"},
        headers={"Authorization": "Bearer secret"},
    )
    # 502 — no providers configured — means auth passed
    assert resp.status_code == 502


def test_empty_search_query_is_400(client):
    resp = client.post("/v1/search", json={"query": "   "})
    assert resp.status_code == 422


def test_search_compat_accepts_api_key_query(client):
    settings.engine_api_key = "secret"
    resp = client.get("/search", params={"q": "acme", "api_key": "wrong"})
    assert resp.status_code == 401
    resp = client.get("/search", params={"q": "acme", "api_key": "secret"})
    assert resp.status_code == 502  # no providers
