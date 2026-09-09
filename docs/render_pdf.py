"""Render docs HTML papers to print PDFs."""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent

JOBS = {
    "method": (
        HERE / "method.html",
        HERE / "Local-LLM-Internet-Engine-Method.pdf",
        "How it works  ·  9 September 2026",
    ),
    "live": (
        HERE / "live-demo.html",
        HERE / "Local-LLM-Internet-Engine-Live-Demo.pdf",
        "Live demo  ·  9 September 2026",
    ),
}


def render(html: Path, pdf: Path, header_right: str) -> Path:
    url = html.resolve().as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.pdf(
            path=str(pdf),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template=(
                '<div style="font-size:8.5pt;color:#6b6459;width:100%;'
                'padding:0 18mm;font-family:Helvetica,Arial,sans-serif;">'
                '<span>Phoenician Capital  ·  local-engine-internet</span>'
                f'<span style="float:right;">{header_right}</span>'
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
    return pdf


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    names = argv or ["live"]
    if names == ["all"]:
        names = list(JOBS)
    for name in names:
        if name not in JOBS:
            raise SystemExit(f"unknown paper: {name}. Try: live | method | all")
        html, pdf, header = JOBS[name]
        print(render(html, pdf, header))


if __name__ == "__main__":
    main()
