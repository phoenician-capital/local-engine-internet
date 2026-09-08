"""Render docs/method.html to a print PDF."""
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
HTML = HERE / "method.html"
PDF = HERE / "Local-LLM-Internet-Engine-Method.pdf"


def main() -> None:
    url = HTML.resolve().as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.pdf(
            path=str(PDF),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template=(
                '<div style="font-size:8.5pt;color:#6b6459;width:100%;'
                'padding:0 18mm;font-family:Helvetica,Arial,sans-serif;">'
                '<span>Phoenician Capital  ·  local-engine-internet</span>'
                '<span style="float:right;">Full method  ·  8 September 2026</span>'
                "</div>"
            ),
            footer_template=(
                '<div style="font-size:9pt;color:#6b6459;width:100%;'
                'text-align:center;font-family:Helvetica,Arial,sans-serif;">'
                '<span class="pageNumber"></span>'
                "</div>"
            ),
            margin={"top": "20mm", "bottom": "18mm", "left": "16mm", "right": "16mm"},
        )
        browser.close()
    print(PDF)


if __name__ == "__main__":
    main()
