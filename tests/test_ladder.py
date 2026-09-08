import httpx
import respx
from httpx import Response

from engine.config import settings
from engine.fetch.ladder import fetch_url, looks_like_decoded_text, looks_like_pdf
from engine.fetch.policy import supported_accept_encoding
from engine.fetch.sec import extract_sec_exhibit_urls


def test_accept_encoding_only_advertises_decodable():
    encodings = supported_accept_encoding()
    assert "gzip" in encodings
    try:
        import brotli  # noqa: F401
        assert "br" in encodings
    except ImportError:
        assert "br" not in encodings


def test_looks_like_decoded_text_rejects_binary():
    assert looks_like_decoded_text("<html><title>Example Domain</title></html>")
    assert not looks_like_decoded_text("\x1b.\x02j{SdgYE\x17|[")


def test_looks_like_pdf_magic_and_rejects_html_disguised():
    assert looks_like_pdf("application/pdf", b"%PDF-1.4 rest", "https://x/a.pdf")
    assert not looks_like_pdf("application/pdf", b"<!doctype html>", "https://x/a.pdf")


@respx.mock
async def test_403_escalates_to_curl_cffi(monkeypatch):
    settings.fetch_mode = "no_browser"
    respx.get("https://blocked.example/doc").mock(return_value=Response(403, text="nope"))

    async def _cffi(url, referer=None):
        html = b"<html><body><p>" + (b"enough text " * 80) + b"</p></body></html>"
        return 200, "text/html", html, url

    monkeypatch.setattr("engine.fetch.ladder.curl_cffi_fetch", _cffi)
    monkeypatch.setattr("engine.fetch.ladder.CURL_CFFI_AVAILABLE", True)

    async with httpx.AsyncClient() as client:
        page = await fetch_url(client, "https://blocked.example/doc", fetch_mode="no_browser")
    assert page.ok
    assert page.tier == "curl_cffi"
    assert "enough text" in page.text


@respx.mock
async def test_httpx_only_does_not_call_cffi(monkeypatch):
    respx.get("https://blocked.example/doc").mock(return_value=Response(403, text="nope"))
    called = {"cffi": False}

    async def _cffi(url, referer=None):
        called["cffi"] = True
        return 200, "text/html", b"<html><body>secret</body></html>", url

    monkeypatch.setattr("engine.fetch.ladder.curl_cffi_fetch", _cffi)
    async with httpx.AsyncClient() as client:
        page = await fetch_url(client, "https://blocked.example/doc", fetch_mode="httpx_only")
    assert not page.ok
    assert called["cffi"] is False


@respx.mock
async def test_thin_html_escalates_to_playwright(monkeypatch):
    thin = "<html><body><p>hi</p></body></html>"
    rich = "<html><body><p>" + ("quarterly results " * 80) + "</p></body></html>"
    respx.get("https://ir.acme.com/events").mock(
        return_value=Response(200, text=thin, headers={"Content-Type": "text/html"})
    )

    async def _pw(url, referer=None):
        return "text/html", rich, rich.encode(), url

    monkeypatch.setattr("engine.fetch.ladder.playwright_fetch", _pw)
    async with httpx.AsyncClient() as client:
        page = await fetch_url(client, "https://ir.acme.com/events", fetch_mode="full")
    assert page.ok
    assert page.tier == "playwright"
    assert "quarterly results" in page.text


@respx.mock
async def test_pdf_bytes_go_through_parser(monkeypatch):
    body = b"%PDF-1.4 fake-pdf-bytes"
    respx.get("https://cdn.example/a.pdf").mock(
        return_value=Response(200, content=body, headers={"Content-Type": "application/pdf"})
    )

    def _pdf_to_text(content, url):
        assert content.startswith(b"%PDF")
        return "Extracted PDF revenue 100"

    monkeypatch.setattr("engine.fetch.ladder.pdf_parser.pdf_to_text", _pdf_to_text)
    async with httpx.AsyncClient() as client:
        page = await fetch_url(client, "https://cdn.example/a.pdf")
    assert page.ok
    assert page.is_pdf
    assert page.tier == "httpx"
    assert "revenue 100" in page.text


@respx.mock
async def test_sec_wrapper_follows_ex991(monkeypatch):
    wrapper = """
    <html><body>
      <a href="/Archives/edgar/data/1/ex-99-1.htm">EX-99.1</a>
    </body></html>
    """
    exhibit = "<html><body><div class='body'>" + ("Earnings release net income " * 80) + "</div></body></html>"
    respx.get("https://www.sec.gov/Archives/edgar/data/1/index.htm").mock(
        return_value=Response(200, text=wrapper, headers={"Content-Type": "text/html"})
    )
    respx.get("https://www.sec.gov/Archives/edgar/data/1/ex-99-1.htm").mock(
        return_value=Response(200, text=exhibit, headers={"Content-Type": "text/html"})
    )
    async with httpx.AsyncClient() as client:
        page = await fetch_url(
            client,
            "https://www.sec.gov/Archives/edgar/data/1/index.htm",
            domain_mode="earnings_doc",
        )
    assert page.ok
    assert page.tier == "sec"
    assert "Earnings release" in page.text
    assert "ex-99-1" in page.final_url


def test_exhibit_url_extraction_priority():
    html = """
    <a href="ex-99-2.htm">EX-99.2</a>
    <a href="ex-99-1.htm">EX-99.1</a>
    <a href="ex-99-1.pdf">EX-99.1 pdf</a>
    """
    urls = extract_sec_exhibit_urls(html, "https://www.sec.gov/Archives/x/")
    assert urls[0].endswith("ex-99-1.pdf")


async def test_social_skipped():
    async with httpx.AsyncClient() as client:
        page = await fetch_url(client, "https://facebook.com/acme")
    assert not page.ok
    assert "blocked" in (page.error or "")
