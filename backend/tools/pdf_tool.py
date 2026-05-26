"""
backend/tools/pdf_tool.py
===========================
PDF Tool — downloads PDF files from URLs, extracts text using
PyMuPDF, and summarizes content using the Groq LLM.

Also wraps the resume parsing pipeline via ResumeAgent.
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import httpx

from backend.config.settings import get_settings
from backend.utils.helpers import sanitize_filename, truncate, utc_now_iso
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

PDF_SUMMARY_PROMPT = """You are an expert document analyst.

Summarize the following PDF document content clearly and concisely.
Return a JSON object with:
{
  "title": "Document title (inferred from content)",
  "summary": "3-5 sentence summary of the document",
  "key_points": ["point 1", "point 2", "..."],
  "document_type": "report|paper|article|form|manual|other",
  "word_count_estimate": 1500
}

Return ONLY valid JSON.

Document text:
"""


class PDFTool:
    """
    Downloads PDFs from the web, extracts text with PyMuPDF,
    and generates LLM-powered summaries.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)
        self.download_dir = Path(settings.upload_dir) / "pdfs"
        self.download_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    async def download_and_analyze(self, url: str) -> Dict[str, Any]:
        """
        Download a PDF from a URL and return its analysis.

        Args:
            url: Direct URL to the PDF file

        Returns:
            Dict with title, summary, key_points, raw_text, local_path
        """
        self.log("info", f"⬇️ Downloading PDF: {url}")

        # Download
        local_path = await self._download_pdf(url)
        if not local_path:
            return {"error": "Failed to download PDF", "url": url}

        self.log("info", f"✅ Downloaded to: {local_path}")

        # Extract text
        raw_text = self._extract_text(local_path)
        if not raw_text:
            return {"error": "No text extractable from PDF", "url": url, "local_path": local_path}

        self.log("info", f"📝 Extracted {len(raw_text)} characters")

        # Summarize
        summary_data = await self._summarize(raw_text)

        return {
            "url": url,
            "local_path": local_path,
            "raw_text_length": len(raw_text),
            "raw_text_preview": raw_text[:500],
            **summary_data,
            "analyzed_at": utc_now_iso(),
        }

    async def parse_resume(self, pdf_path: str) -> Dict[str, Any]:
        """
        Parse a resume PDF and return a structured candidate profile.
        Delegates to ResumeAgent.
        """
        from backend.agents.resume_agent import ResumeAgent
        agent = ResumeAgent(log_callback=self.log)
        return await agent.parse(pdf_path)

    def extract_text_only(self, pdf_path: str) -> str:
        """Extract raw text from a local PDF file."""
        return self._extract_text(pdf_path)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _download_pdf(self, url: str) -> Optional[str]:
        """Download PDF from URL to local disk. Returns file path or None."""
        try:
            # Generate deterministic filename from URL
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"pdf_{url_hash}.pdf"
            dest = self.download_dir / filename

            # Skip if already downloaded
            if dest.exists():
                self.log("info", "📎 PDF already cached locally")
                return str(dest)

            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; AutonomousAgent/1.0)"},
                )
                response.raise_for_status()

                # Verify it's actually a PDF
                content_type = response.headers.get("content-type", "")
                if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
                    logger.warning(f"URL may not be a PDF (content-type: {content_type})")

                with open(dest, "wb") as f:
                    f.write(response.content)

            return str(dest)

        except Exception as exc:
            logger.error(f"PDF download failed ({url}): {exc}")
            self.log("error", f"❌ Download failed: {exc}")
            return None

    def _extract_text(self, pdf_path: str) -> str:
        """Extract all text from a PDF using PyMuPDF (fitz)."""
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(pdf_path)
            pages = []
            for page_num, page in enumerate(doc):
                text = page.get_text("text")
                if text.strip():
                    pages.append(f"[Page {page_num + 1}]\n{text}")
            doc.close()
            return "\n\n".join(pages)

        except Exception as exc:
            logger.error(f"PyMuPDF text extraction failed ({pdf_path}): {exc}")
            return ""

    async def _summarize(self, text: str) -> Dict[str, Any]:
        """Use Groq LLM to summarize PDF content."""
        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import HumanMessage, SystemMessage
            from backend.utils.helpers import extract_json_block

            llm = ChatGroq(
                api_key=settings.groq_api_key,
                model=settings.groq_model_primary,
                temperature=0.0,
                max_tokens=1500,
            )

            truncated = truncate(text, 5000)
            messages = [
                SystemMessage(content=PDF_SUMMARY_PROMPT),
                HumanMessage(content=truncated),
            ]

            response = await llm.ainvoke(messages)
            result = extract_json_block(response.content)

            if isinstance(result, dict):
                return result
            return {"summary": response.content[:500], "key_points": [], "title": "Document"}

        except Exception as exc:
            logger.error(f"PDF summarization failed: {exc}")
            return {
                "summary": f"Text extracted ({len(text)} chars). LLM summarization failed: {exc}",
                "key_points": [],
                "title": "Document",
                "document_type": "unknown",
            }
