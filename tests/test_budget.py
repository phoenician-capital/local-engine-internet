from engine.budget import ToolBudget


def test_search_and_fetch_caps():
    b = ToolBudget(max_search_uses=1, max_fetches=2, max_rounds=3, web_context_chars=1000)
    assert b.allow_search()
    b.note_search()
    assert not b.allow_search()
    b.note_fetch()
    b.note_fetch()
    assert not b.allow_fetch()


def test_compacts_oldest_tool_outputs_first():
    b = ToolBudget(max_search_uses=8, max_fetches=8, max_rounds=6, web_context_chars=80)
    messages = [
        {"role": "user", "content": "q"},
        {"role": "tool", "tool_call_id": "1", "content": "[PUBLIC_URL: https://a.example]\n" + ("x" * 200)},
        {"role": "tool", "tool_call_id": "2", "content": "short keep"},
    ]
    b.trim_tool_messages(messages)
    assert messages[1]["content"].startswith("[compacted:")
    assert "https://a.example" in messages[1]["content"]
    assert messages[2]["content"] == "short keep"
