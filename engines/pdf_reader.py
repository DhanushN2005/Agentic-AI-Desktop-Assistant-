import os
import re
from typing import Optional

try:
    import fitz  # PyMuPDF
    _PDF_OK = True
except ImportError:
    _PDF_OK = False


class PDFReaderEngine:
    """Local PDF reader using PyMuPDF (no API key required)."""

    def __init__(self):
        self._available = _PDF_OK

    def _check(self) -> Optional[str]:
        if not self._available:
            return "PDF reader not available. Install with: pip install pymupdf"
        return None

    def read_pdf(self, filepath: str) -> str:
        err = self._check()
        if err:
            return err
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        try:
            doc = fitz.open(filepath)
            text_parts = []
            for i, page in enumerate(doc):
                text = page.get_text()
                if text.strip():
                    text_parts.append(f"--- Page {i+1} ---\n{text.strip()}")
            doc.close()
            if not text_parts:
                return "PDF contains no readable text."
            full_text = "\n\n".join(text_parts)
            if len(full_text) > 3000:
                full_text = full_text[:3000] + "\n... [truncated]"
            return f"PDF content ({len(text_parts)} pages):\n{full_text}"
        except Exception as e:
            return f"Error reading PDF: {e}"

    def summarize_pdf(self, filepath: str, max_pages: int = 5) -> str:
        err = self._check()
        if err:
            return err
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        try:
            doc = fitz.open(filepath)
            text_parts = []
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                text = page.get_text()
                if text.strip():
                    text_parts.append(text.strip())
            doc.close()
            if not text_parts:
                return "PDF contains no readable text."
            combined = " ".join(text_parts)
            sentences = re.split(r'[.!?]+', combined)
            summary = ". ".join(s.strip() for s in sentences[:10] if s.strip())
            if len(summary) > 500:
                summary = summary[:500] + "..."
            return f"Summary of {os.path.basename(filepath)}: {summary}."
        except Exception as e:
            return f"Error summarizing PDF: {e}"

    def get_info(self, filepath: str) -> str:
        err = self._check()
        if err:
            return err
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        try:
            doc = fitz.open(filepath)
            info = {
                "pages": len(doc),
                "title": doc.metadata.get("title", "Unknown"),
                "author": doc.metadata.get("author", "Unknown"),
                "size": f"{os.path.getsize(filepath) / 1024:.1f} KB",
            }
            doc.close()
            return f"PDF Info: {info['pages']} pages, title: {info['title']}, author: {info['author']}, size: {info['size']}."
        except Exception as e:
            return f"Error reading PDF info: {e}"
