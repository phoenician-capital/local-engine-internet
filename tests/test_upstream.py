from engine.agent.upstream import prepare_upstream_body
from engine.config import settings


def test_prepare_body_disables_thinking_on_deepseek_cloud_forced_choice(monkeypatch):
    monkeypatch.setattr(settings, "upstream_llm_base_url", "https://api.deepseek.com")
    body = {
        "model": "deepseek-v4-flash",
        "tool_choice": {"type": "function", "function": {"name": "web_search"}},
        "messages": [],
    }
    out = prepare_upstream_body(body)
    assert out["thinking"] == {"type": "disabled"}
    assert "thinking" not in body


def test_prepare_body_leaves_local_router_alone(monkeypatch):
    monkeypatch.setattr(settings, "upstream_llm_base_url", "http://127.0.0.1:8080")
    body = {
        "tool_choice": {"type": "function", "function": {"name": "web_search"}},
        "messages": [],
    }
    assert "thinking" not in prepare_upstream_body(body)


def test_prepare_body_auto_on_cloud_does_not_force_thinking(monkeypatch):
    monkeypatch.setattr(settings, "upstream_llm_base_url", "https://api.deepseek.com")
    out = prepare_upstream_body({"tool_choice": "auto", "messages": []})
    assert "thinking" not in out
