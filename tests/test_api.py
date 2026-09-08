from engine.config import settings


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "providers_configured" in body


def test_capabilities_lists_vllm_flags(client):
    resp = client.get("/capabilities")
    assert resp.status_code == 200
    flags = resp.json()["vllm_required_flags"]
    assert "--tool-call-parser deepseek_v4" in flags
    assert "--enable-auto-tool-choice" in flags


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


def test_search_compat_accepts_api_key_query(client):
    settings.engine_api_key = "secret"
    resp = client.get("/search", params={"q": "acme", "api_key": "wrong"})
    assert resp.status_code == 401
    resp = client.get("/search", params={"q": "acme", "api_key": "secret"})
    assert resp.status_code == 502  # no providers
