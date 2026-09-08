from engine.search.query import (
    build_simple_queries,
    clean_company,
    filetype_pdf,
    site_query,
)


def test_strips_legal_suffixes():
    assert clean_company("Acme Corp.") == "Acme"
    assert clean_company("Foo PLC") == "Foo"
    assert clean_company("Bar Limited") == "Bar"


def test_site_and_filetype_builders():
    assert site_query("https://www.ir.acme.com/page", "earnings") == "site:ir.acme.com earnings"
    assert filetype_pdf("Acme earnings") == "Acme earnings filetype:pdf"
    assert "filetype:pdf" in filetype_pdf("already filetype:pdf")


def test_build_simple_queries_includes_pdf_and_site():
    qs = build_simple_queries("ACME.O", "Acme Inc", "Q2", 2026, ir_domain="https://ir.acme.com")
    assert any("filetype:pdf" in q for q in qs)
    assert any(q.startswith("site:ir.acme.com") for q in qs)
    assert any('"ACME"' in q for q in qs)
    assert len(qs) <= 15
    assert len(qs) == len(set(qs))
