from engine.fetch.extract import extract_html, html_to_text


def test_html_to_text_strips_chrome_and_unescapes():
    html = """
    <html><head><title>Ignore</title><script>var x=1</script></head>
    <body>
      <h1>Revenue</h1>
      <p>Net sales &amp; EPS&nbsp;$1.2</p>
      <div>Cookie Policy</div>
    </body></html>
    """
    text = html_to_text(html)
    assert "Revenue" in text
    assert "Net sales & EPS $1.2" in text
    assert "var x" not in text
    assert "Cookie Policy" not in text


def test_extract_html_fallback_when_trafilatura_empty(monkeypatch):
    import engine.fetch.extract as extract_mod

    class _Fake:
        @staticmethod
        def extract(*_a, **_k):
            return None

        @staticmethod
        def extract_metadata(*_a, **_k):
            return None

    monkeypatch.setattr(extract_mod, "trafilatura", _Fake)
    monkeypatch.setattr(extract_mod, "_TRAFILATURA", True)
    html = "<html><head><title>Doc Title</title></head><body><p>Hello body</p></body></html>"
    text, title, canonical = extract_html(
        html,
        url="https://ir.acme.com/x",
        max_chars=20,
    )
    assert "Hello" in text
    assert title == "Doc Title"
    assert len(text) <= 20


def test_extract_respects_max_chars():
    html = "<html><body>" + ("word " * 5000) + "</body></html>"
    text, _title, _c = extract_html(html, max_chars=100)
    assert len(text) <= 100
