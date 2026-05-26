"""
backend/agents/extraction_agent.py
====================================
Extraction Agent — uses Groq LLM to turn raw page text / HTML
into clean, structured JSON data.

Handles:
- Job listing extraction
- General data extraction from page content
- Deduplication by content hash
"""

import json
from typing import Any, Callable, Dict, List, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config.settings import get_settings
from backend.utils.helpers import extract_json_block, hash_string, truncate
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

JOB_EXTRACTION_PROMPT = """You are a precise data extraction AI agent.

Extract ALL job listings from the page text below. For each job, extract:
- company: Company name
- role: Job title / position
- location: City, country, or "Remote"
- salary: Stipend or salary if mentioned, else "Not specified"
- skills: List of required skills/technologies (array of strings)
- apply_link: Application URL if found, else ""
- description: Brief job description (1-2 sentences)
- job_type: "internship" | "full-time" | "part-time" | "contract"

Return ONLY a JSON array. If no jobs found, return an empty array [].

Example output:
[
  {
    "company": "TechCorp",
    "role": "GenAI Intern",
    "location": "Remote",
    "salary": "₹15,000/month",
    "skills": ["Python", "LangChain", "RAG"],
    "apply_link": "https://example.com/apply",
    "description": "Work on cutting-edge AI products.",
    "job_type": "internship"
  }
]

Page text to extract from:
"""

GENERAL_EXTRACTION_PROMPT = """You are a precise data extraction AI.

Extract the most relevant structured information from the page text below.
Return a clean JSON object with the key data points found.
Focus on: facts, names, links, dates, prices, and key information.

Return ONLY valid JSON. No explanation.

Page text:
"""


class ExtractionAgent:
    """
    Uses Groq LLM to extract structured data from raw browser page text.
    Supports job listing extraction and generic data extraction.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)
        self.llm = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model_primary,
            temperature=0.0,
            max_tokens=4096,
        )
        self._seen_hashes: set = set()  # For deduplication

    async def extract_jobs(self, page_text: str, source_url: str = "") -> List[Dict[str, Any]]:
        """
        Extract job listings from page text.
        Returns deduplicated list of structured job objects.
        """
        if not page_text.strip():
            return []

        self.log("info", f"📊 Extracting jobs from page ({len(page_text)} chars)…")

        truncated_text = truncate(page_text, 6000)

        messages = [
            SystemMessage(content=JOB_EXTRACTION_PROMPT),
            HumanMessage(content=truncated_text),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            jobs = extract_json_block(response.content)

            if not isinstance(jobs, list):
                jobs = []

            # Add source and deduplicate
            unique_jobs = []
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                # Add source URL
                job["source_url"] = source_url
                # Dedup by company+role hash
                key = hash_string(f"{job.get('company', '')}{job.get('role', '')}")
                if key not in self._seen_hashes:
                    self._seen_hashes.add(key)
                    unique_jobs.append(job)

            self.log("success", f"✅ Extracted {len(unique_jobs)} unique jobs")
            return unique_jobs

        except Exception as exc:
            logger.error(f"Job extraction failed: {exc}")
            self.log("warn", f"⚠️ Extraction failed: {exc}")
            return []

    async def extract_general(self, page_text: str) -> Dict[str, Any]:
        """
        Extract general structured data from any page text.
        Returns a dict of key-value pairs.
        """
        if not page_text.strip():
            return {}

        truncated_text = truncate(page_text, 5000)
        messages = [
            SystemMessage(content=GENERAL_EXTRACTION_PROMPT),
            HumanMessage(content=truncated_text),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            result = extract_json_block(response.content)
            return result if isinstance(result, dict) else {"raw": response.content[:1000]}
        except Exception as exc:
            logger.error(f"General extraction failed: {exc}")
            return {"error": str(exc)}

    def reset_dedup(self) -> None:
        """Reset the deduplication hash set (call between tasks)."""
        self._seen_hashes.clear()
