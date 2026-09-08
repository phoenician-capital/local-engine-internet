from engine.search.brave import parse_brave_payload
from engine.search.tavily import parse_tavily_payload


def test_tavily_parses_answer_and_results():
    hits = parse_tavily_payload(
        {
            "answer": "Acme is a widget maker.",
            "results": [
                {
                    "title": "Acme",
                    "url": "https://acme.example",
                    "content": "Widgets since 1901.",
                    "published_date": "2026-01-01",
                }
            ],
        },
        query="acme",
    )
    assert hits[0].kind == "answer_box"
    assert hits[0].source == "tavily"
    assert hits[1].url == "https://acme.example"
    assert hits[1].date == "2026-01-01"


def test_brave_parses_web_news_and_extra_snippets():
    hits = parse_brave_payload(
        {
            "web": {
                "results": [
                    {
                        "title": "Acme",
                        "url": "https://acme.example",
                        "description": "Main.",
                        "extra_snippets": ["More detail here."],
                    }
                ]
            },
            "news": {
                "results": [
                    {
                        "title": "Acme news",
                        "url": "https://news.example/acme",
                        "description": "Filed today.",
                    }
                ]
            },
        },
        query="acme",
    )
    assert hits[0].snippet == "Main. More detail here."
    assert hits[1].url == "https://news.example/acme"
    assert hits[1].source == "brave"
