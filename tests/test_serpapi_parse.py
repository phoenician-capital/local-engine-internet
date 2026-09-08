import json
from pathlib import Path

from engine.search.serpapi import extras_from_payload, parse_serpapi_payload

SAMPLE = json.loads(
    (Path(__file__).parent / "fixtures" / "serpapi_sample.json").read_text()
)


def test_parses_organic_answer_box_kg_and_two_related():
    hits = parse_serpapi_payload(SAMPLE, query="acme earnings")
    kinds = [h.kind for h in hits]
    assert kinds.count("answer_box") == 1
    assert kinds.count("knowledge_graph") == 1
    assert kinds.count("related_question") == 2
    organics = [h for h in hits if h.kind == "organic"]
    # Duplicate snippet and duplicate URL are dropped inside the parser.
    assert len(organics) == 1
    assert organics[0].url == "https://ir.acme.com/q2-2026"
    assert organics[0].source == "serpapi"
    box = next(h for h in hits if h.kind == "answer_box")
    assert "August 1" in box.snippet
    kg = next(h for h in hits if h.kind == "knowledge_graph")
    assert "NYSE: ACME" in kg.snippet


def test_extras_keep_raw_blocks():
    extras = extras_from_payload(SAMPLE)
    assert extras["answer_box"]["link"] == "https://ir.acme.com/calendar"
    assert extras["knowledge_graph"]["title"] == "Acme Corp"
    assert len(extras["related_questions"]) == 2
