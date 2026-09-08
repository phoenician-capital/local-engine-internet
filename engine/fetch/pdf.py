"""PDF text extraction: pdfplumber → PyMuPDF → pypdf → pdftotext → regex.

Port of Earnings_tracker/tracker/summary/pdf_parser.py.
"""
from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import tempfile
import warnings
from typing import Optional

from ..config import settings

logger = logging.getLogger("engine.fetch.pdf")

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import fitz  # PyMuPDF

    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    from pypdf import PdfReader

    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


class PDFParser:
    def __init__(self) -> None:
        self._parser_used: Optional[str] = None

    def pdf_to_text(self, content: bytes, url: str) -> Optional[str]:
        max_bytes = settings.max_pdf_bytes
        if not content or len(content) > max_bytes:
            logger.debug("PDF too large (%s bytes), skipping: %s", len(content or b""), url[:80])
            return None

        text = None
        parser_used = None

        if HAS_PDFPLUMBER and not text:
            try:
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    pages_text = []
                    for page in pdf.pages:
                        page_text = page.extract_text() or ""
                        if page_text.strip():
                            pages_text.append(page_text)
                    if pages_text:
                        text = "\n".join(pages_text)
                        parser_used = "pdfplumber"
            except Exception as exc:
                logger.debug("pdfplumber failed: %s", exc)

        if HAS_FITZ and not text:
            try:
                doc = fitz.open(stream=io.BytesIO(content), filetype="pdf")
                pages_text = []
                for page_num in range(len(doc)):
                    page_text = doc[page_num].get_text()
                    if page_text.strip():
                        pages_text.append(page_text)
                doc.close()
                if pages_text:
                    text = "\n".join(pages_text)
                    parser_used = "fitz"
            except Exception as exc:
                logger.debug("PyMuPDF failed: %s", exc)

        if HAS_PYPDF and not text:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    reader = PdfReader(io.BytesIO(content), strict=False)
                pages_text = []
                for page in reader.pages:
                    try:
                        page_text = page.extract_text() or ""
                    except Exception:
                        continue
                    if page_text.strip():
                        pages_text.append(page_text)
                if pages_text:
                    text = "\n".join(pages_text)
                    parser_used = "pypdf"
            except Exception as exc:
                logger.debug("pypdf failed: %s", exc)

        if not text:
            text = self._pdf_to_text_poppler(content)
            if text:
                parser_used = "poppler"

        if not text:
            try:
                raw_text = content.decode("latin-1", errors="ignore")
                readable = re.findall(r"[A-Za-z][A-Za-z0-9\s.,$%()\-]{3,}", raw_text)
                if readable:
                    raw_text = " ".join(readable)
                    raw_text = re.sub(r"[^\x20-\x7E]+", " ", raw_text)
                    raw_text = re.sub(r"\s+", " ", raw_text).strip()
                    if len(raw_text) > 100:
                        text = raw_text
                        parser_used = "raw_regex"
            except Exception as exc:
                logger.debug("raw regex fallback failed: %s", exc)

        if text:
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
            text = text.strip()
            self._parser_used = parser_used
            logger.info("PDF parsed with %s: %s chars from %s", parser_used, len(text), url[:80])
            return text

        logger.warning("All PDF parsers failed for %s", url[:80])
        return f"This document is a PDF report available at: {url}"

    def _pdf_to_text_poppler(self, content: bytes) -> Optional[str]:
        temp_pdf = None
        temp_txt = None
        try:
            try:
                subprocess.run(["pdftotext", "-v"], capture_output=True, timeout=2)
            except (subprocess.SubprocessError, FileNotFoundError):
                return None
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(content)
                temp_pdf = f.name
            temp_txt = tempfile.NamedTemporaryFile(suffix=".txt", delete=False).name
            result = subprocess.run(
                ["pdftotext", "-layout", temp_pdf, temp_txt],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0 and os.path.exists(temp_txt):
                with open(temp_txt, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                    if text and len(text) > 100:
                        return text
        except Exception as exc:
            logger.debug("pdftotext failed: %s", exc)
        finally:
            for path in (temp_pdf, temp_txt):
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except Exception:
                        pass
        return None


pdf_parser = PDFParser()
