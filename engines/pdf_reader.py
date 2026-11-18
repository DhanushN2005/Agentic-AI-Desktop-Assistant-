import logging
import os
import re

try:
    from pypdf import PdfReader  # pypdf: BSD-3-Clause, MIT-compatible
    _PDF_OK = True
except ImportError as _e:
    logging.debug("[engines/pdf_reader.py] pypdf unavailable: %s: %s", type(_e).__name__, _e)
    PdfReader = None  # type: ignore[assignment]
    _PDF_OK = False


class PDFReaderEngine:
    """Local PDF reader using pypdf (no API key required)."""

    def __init__(self):
        self._available = _PDF_OK

    def _check(self) -> str | None:
        if not self._available:
            return "PDF reader not available. Install with: pip install pypdf"
        return None

    @staticmethod
    def _page_texts(reader, max_pages: int | None = None,
                    max_chars: int | None = None) -> list[tuple[int, str]]:
        """Extract (page_number, text) pairs, tolerating individual unreadable pages.
        Stops extracting as soon as max_pages pages were visited or max_chars of
        text were collected, so a 1000-page PDF is never fully parsed for a preview."""
        pages: list[tuple[int, str]] = []
        collected = 0
        for i, page in enumerate(reader.pages):
            if max_pages is not None and i >= max_pages:
                break
            if max_chars is not None and collected >= max_chars:
                break
            try:
                text = page.extract_text() or ""
            except Exception as e:  # one bad page must not abort the whole document
                logging.warning("[engines/pdf_reader.py] page %d extraction failed: %s", i + 1, e)
                continue
            if text.strip():
                pages.append((i + 1, text.strip()))
                collected += len(text)
        return pages

    def read_pdf(self, filepath: str) -> str:
        err = self._check()
        if err:
            return err
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        try:
            reader = PdfReader(filepath)
            total_pages = len(reader.pages)
            text_parts = [
                f"--- Page {number} ---\n{text}"
                for number, text in self._page_texts(reader, max_chars=3000)
            ]
            if not text_parts:
                return "PDF contains no readable text."
            full_text = "\n\n".join(text_parts)
            if len(full_text) > 3000:
                full_text = full_text[:3000] + "\n... [truncated]"
            return f"PDF content (showing {len(text_parts)} of {total_pages} pages):\n{full_text}"
        except Exception as e:
            logging.warning("[engines/pdf_reader.py] failed to read %s: %s", filepath, e)
            return f"Error reading PDF: {e}"

    def summarize_pdf(self, filepath: str, max_pages: int = 5) -> str:
        err = self._check()
        if err:
            return err
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        try:
            reader = PdfReader(filepath)
            pages = self._page_texts(reader, max_pages=max_pages)
            if not pages:
                return "PDF contains no readable text."
            combined = " ".join(text for _, text in pages)
            sentences = re.split(r"[.!?]+", combined)
            summary = ". ".join(s.strip() for s in sentences[:10] if s.strip())
            if len(summary) > 500:
                summary = summary[:500] + "..."
            total = len(reader.pages)
            scope = f" (first {min(max_pages, total)} of {total} pages)" if total > max_pages else f" ({total} pages)"
            return f"Summary of {os.path.basename(filepath)}{scope}: {summary}."
        except Exception as e:
            logging.warning("[engines/pdf_reader.py] failed to summarize %s: %s", filepath, e)
            return f"Error summarizing PDF: {e}"

    def get_info(self, filepath: str) -> str:
        err = self._check()
        if err:
            return err
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        try:
            reader = PdfReader(filepath)
            meta = reader.metadata or {}
            info = {
                "pages": len(reader.pages),
                "title": meta.get("/Title") or "Unknown",
                "author": meta.get("/Author") or "Unknown",
                "size": f"{os.path.getsize(filepath) / 1024:.1f} KB",
            }
            return (
                f"PDF Info: {info['pages']} pages, title: {info['title']}, "
                f"author: {info['author']}, size: {info['size']}."
            )
        except Exception as e:
            logging.warning("[engines/pdf_reader.py] failed to read info for %s: %s", filepath, e)
            return f"Error reading PDF info: {e}"
