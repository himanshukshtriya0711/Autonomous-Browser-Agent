"""
backend/tools/extraction_tool.py
===================================
Extraction Tool — high-level API wrapping ExtractionAgent for use
in tool chains. Provides structured data extraction from:
- Raw HTML / page text
- JSON-LD structured data embedded in pages
- Open Graph / meta tags
- Tables
"""

import json
import re
from typing import Any, Callable, Dict, List, Optional

from bs4 import BeautifulSoup

from backend.utils.helpers import clean_text, truncate
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class ExtractionTool:
    """
    Multi-strategy data extractor.

    Strategy priority:
    1. JSON-LD structured data (most reliable)
    2. Open Graph / meta tags
    3. HTML table parsing
    4. LLM extraction (fallback)
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)

    async def extract_from_html(self, html: str, task: str = "general") -> Dict[str, Any]:
        """
        Extract structured data from raw HTML.

        Args:
            html: Raw HTML string
            task: Extraction task hint ("jobs", "general", "contacts", "prices")

        Returns:
            Structured dict of extracted data
        """
        result: Dict[str, Any] = {}

        # Strategy 1: JSON-LD
        jsonld = self._extract_jsonld(html)
        if jsonld:
            result["structured_data"] = jsonld
            self.log("info", "✅ Extracted JSON-LD structured data")

        # Strategy 2: Meta / Open Graph
        meta = self._extract_meta(html)
        if meta:
            result["meta"] = meta

        # Strategy 3: Tables
        tables = self._extract_tables(html)
        if tables:
            result["tables"] = tables

        # Strategy 4: LLM fallback for the visible text
        if not result or task == "jobs":
            soup = BeautifulSoup(html, "lxml")
            text = clean_text(soup.get_text(separator=" "))
            if text:
                from backend.agents.extraction_agent import ExtractionAgent
                agent = ExtractionAgent(log_callback=self.log)
                if task == "jobs":
                    result["jobs"] = await agent.extract_jobs(text)
                else:
                    llm_data = await agent.extract_general(text)
                    result["extracted"] = llm_data

        return result

    async def extract_jobs_from_html(self, html: str, source_url: str = "") -> List[Dict[str, Any]]:
        """Extract job listings specifically from HTML."""
        from backend.agents.extraction_agent import ExtractionAgent

        soup = BeautifulSoup(html, "lxml")
        text = clean_text(soup.get_text(separator=" "))

        agent = ExtractionAgent(log_callback=self.log)
        return await agent.extract_jobs(truncate(text, 6000), source_url)

    def extract_contacts(self, text: str) -> Dict[str, List[str]]:
        """
        Extract contact information from text using regex.
        Returns emails, phones, and social profile URLs.
        """
        result: Dict[str, List[str]] = {"emails": [], "phones": [], "linkedin": [], "github": []}

        # Emails
        result["emails"] = list(set(re.findall(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text)))

        # Phones
        result["phones"] = list(set(re.findall(r"(\+?\d[\d\s\-().]{8,}\d)", text)))[:5]

        # LinkedIn
        result["linkedin"] = [
            f"https://{m}" for m in re.findall(r"linkedin\.com/in/[\w-]+", text, re.IGNORECASE)
        ]

        # GitHub
        result["github"] = [
            f"https://{m}" for m in re.findall(r"github\.com/[\w-]+", text, re.IGNORECASE)
        ]

        return result

    def extract_prices(self, text: str) -> List[str]:
        """Extract price mentions from text."""
        patterns = [
            r"₹[\d,]+(?:\.\d{1,2})?(?:\s*(?:lakh|k|crore))?",
            r"\$[\d,]+(?:\.\d{1,2})?(?:\s*(?:k|million))?",
            r"USD\s*[\d,]+",
            r"INR\s*[\d,]+",
        ]
        prices = []
        for pattern in patterns:
            prices.extend(re.findall(pattern, text, re.IGNORECASE))
        return list(set(prices))

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_jsonld(self, html: str) -> Optional[List[Dict]]:
        """Extract JSON-LD structured data from <script type="application/ld+json"> tags."""
        try:
            soup = BeautifulSoup(html, "lxml")
            results = []
            for tag in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(tag.string or "")
                    results.append(data)
                except json.JSONDecodeError:
                    continue
            return results if results else None
        except Exception:
            return None

    def _extract_meta(self, html: str) -> Dict[str, str]:
        """Extract Open Graph and standard meta tags."""
        try:
            soup = BeautifulSoup(html, "lxml")
            meta: Dict[str, str] = {}

            # Title
            title = soup.find("title")
            if title:
                meta["title"] = clean_text(title.get_text())

            # Meta tags
            for tag in soup.find_all("meta"):
                name = tag.get("property") or tag.get("name") or ""
                content = tag.get("content", "")
                if name and content:
                    meta[name] = content[:200]

            return meta
        except Exception:
            return {}

    def _extract_tables(self, html: str) -> List[List[List[str]]]:
        """Extract data from HTML tables."""
        try:
            soup = BeautifulSoup(html, "lxml")
            tables = []
            for table in soup.find_all("table")[:5]:  # Limit to 5 tables
                rows = []
                for row in table.find_all("tr"):
                    cells = [clean_text(cell.get_text()) for cell in row.find_all(["td", "th"])]
                    if any(cells):
                        rows.append(cells)
                if rows:
                    tables.append(rows)
            return tables
        except Exception:
            return []
