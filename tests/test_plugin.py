from engine import runtime
from engine.agent.loop import strip_engine_tools, strip_extension_keys
from engine.api.chat import _outbound_chat_body, _should_run_loop
from engine.config import settings
from engine.plugin import intelligence_policy, plugin_enabled, plugin_status
from engine.tools.schemas import WEB_SEARCH_SCHEMA


def test_welcome_and_health_expose_plugin(client):
    welcome = client.get("/").json()
    assert welcome["ui"] == "/ui"
    assert welcome["plugin"]["enabled"] is True
    assert welcome["plugin"]["intelligence"] == "auto"
    health = client.get("/health").json()
    assert health["plugin"]["layers"]["1_master"] == "enabled"
    assert health["plugin"]["layers"]["2_intelligence"] == "auto"


def test_plugin_toggle_blocks_mode1(client):
    status = client.get("/v1/plugin").json()
    assert status["enabled"] is True
    assert status["intelligence"] == "auto"

    off = client.post("/v1/plugin", json={"enabled": False}).json()
    assert off["enabled"] is False
    assert off["intelligence"] == "off"
    assert off["search_ready"] is False

    resp = client.post("/v1/search", json={"query": "acme"})
    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()

    resp = client.post("/v1/fetch", json={"url": "https://example.com"})
    assert resp.status_code == 503

    resp = client.get("/search", params={"q": "acme"})
    assert resp.status_code == 503

    on = client.post("/v1/plugin", json={"enabled": True}).json()
    assert on["enabled"] is True
    # No providers in tests — search is 502, not 503.
    resp = client.post("/v1/search", json={"query": "acme"})
    assert resp.status_code == 502


def test_request_header_disables_without_global_off(client):
    resp = client.post(
        "/v1/search",
        json={"query": "acme"},
        headers={"X-Phoenician-Plugin": "off"},
    )
    assert resp.status_code == 503
    assert client.get("/v1/plugin").json()["enabled"] is True


def test_global_off_wins_over_request_on():
    runtime.plugin_enabled = False
    assert plugin_enabled({"enabled": True}, {"x-phoenician-plugin": "on"}) is False
    assert intelligence_policy({"policy": "required"}, None).value == "off"


def test_body_enabled_false_is_passthrough():
    assert plugin_enabled({"enabled": False}, None) is False
    assert _should_run_loop(
        {"messages": [{"role": "user", "content": "hi"}], "phoenician_web": {"enabled": False}}
    ) is False


def test_intelligence_auto_when_plugin_on():
    runtime.plugin_enabled = True
    assert plugin_enabled({}, None) is True
    assert intelligence_policy({}, None).value == "auto"
    assert _should_run_loop({"messages": [{"role": "user", "content": "hi"}]}) is True
    assert _should_run_loop(
        {"messages": [{"role": "user", "content": "hi"}], "phoenician_web": {"policy": "off"}}
    ) is False
    assert _should_run_loop({"phoenician_tools": []}) is False


def test_plugin_status_explains_layers():
    status = plugin_status()
    assert "master switch" in status["explain"]["1"]
    assert "model decides" in status["explain"]["2"]


def test_ui_page(client):
    resp = client.get("/ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Layer 1" in resp.text
    assert "Layer 2" in resp.text
    assert "/v1/plugin" in resp.text
    assert "ENGINE_API_KEY" in resp.text
    assert "r.ok" in resp.text


def test_plugin_off_does_not_start_tool_loop():
    runtime.plugin_enabled = False
    assert (
        _should_run_loop(
            {
                "stream": True,
                "phoenician_tools": ["web_search"],
                "messages": [{"role": "user", "content": "hi"}],
            }
        )
        is False
    )


def test_default_policy_off_skips_loop_including_stream():
    settings.default_web_policy = "off"
    body = {"stream": True, "messages": [{"role": "user", "content": "hi"}]}
    assert _should_run_loop(body) is False
    assert intelligence_policy({}, None).value == "off"


def test_strip_extension_keys_and_engine_tools():
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "phoenician_tools": ["web_search"],
        "phoenician_web": {"enabled": True},
        "tools": [WEB_SEARCH_SCHEMA, {"type": "function", "function": {"name": "other"}}],
        "tool_choice": "auto",
    }
    stripped = strip_extension_keys(body)
    assert "phoenician_tools" not in stripped
    assert "phoenician_web" not in stripped
    assert "tools" in stripped
    cleaned = strip_engine_tools(dict(stripped))
    assert [t["function"]["name"] for t in cleaned["tools"]] == ["other"]


def test_outbound_stream_body_strips_when_plugin_off():
    runtime.plugin_enabled = False
    out = _outbound_chat_body(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "phoenician_web": {"policy": "required"},
            "tools": [WEB_SEARCH_SCHEMA],
            "tool_choice": "auto",
        }
    )
    assert "phoenician_web" not in out
    assert "tools" not in out
    assert "tool_choice" not in out
