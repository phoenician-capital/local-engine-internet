from engine.tools.dsml_fallback import recover_tool_calls


def test_recovers_dsml_invoke_block():
    content = (
        'preamble <｜DSML｜invoke name="web_search">'
        '<｜DSML｜parameter name="query">acme 2026 earnings</｜DSML｜parameter>'
        "</｜DSML｜invoke> leftover"
    )
    calls = recover_tool_calls(content)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "web_search"
    assert "acme 2026 earnings" in calls[0]["function"]["arguments"]


def test_recovers_open_invoke_without_closer():
    content = (
        '<｜DSML｜invoke name="fetch_url">'
        '<｜DSML｜parameter name="url">https://ir.acme.com/q2</｜DSML｜parameter>'
    )
    calls = recover_tool_calls(content)
    assert calls[0]["function"]["name"] == "fetch_url"
    assert "ir.acme.com" in calls[0]["function"]["arguments"]


def test_recovers_deepseek_tool_markup():
    content = (
        "<|tool▁calls▁begin|><|tool▁call▁begin|>"
        "function<|tool▁sep|>web_search\n"
        '```json\n{"query": "phoenician capital"}\n```\n'
        "<|tool▁call▁end|><|tool▁calls▁end|>"
    )
    calls = recover_tool_calls(content)
    assert calls[0]["function"]["name"] == "web_search"
    assert "phoenician capital" in calls[0]["function"]["arguments"]


def test_empty_or_prose_returns_nothing():
    assert recover_tool_calls("Just an answer with no tools.") == []
    assert recover_tool_calls(None) == []
