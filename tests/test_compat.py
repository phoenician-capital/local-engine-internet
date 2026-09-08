from engine.api.compat import hits_to_serpapi_shape
from engine.search.base import Hit, SearchOutcome


def test_compat_shape_from_hits():
    outcome = SearchOutcome(
        hits=[
            Hit("One", "https://a.example", "snip", "serpapi", kind="organic", position=1),
            Hit("Answer Box", "https://b.example", "the answer", "serpapi", kind="answer_box"),
            Hit("Knowledge Graph", "https://c.example", "desc", "serpapi", kind="knowledge_graph"),
            Hit("Related: When?", "https://d.example", "When? soon", "serpapi", kind="related_question"),
        ]
    )
    payload = hits_to_serpapi_shape(outcome)
    assert payload["organic_results"][0]["link"] == "https://a.example"
    assert payload["organic_results"][0]["title"] == "One"
    assert payload["answer_box"]["answer"] == "the answer"
    assert payload["knowledge_graph"]["title"] == "Knowledge Graph"
    assert payload["related_questions"][0]["link"] == "https://d.example"
