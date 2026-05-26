"""
backend/agents/resume_agent.py
================================
Resume Agent — parses uploaded PDF resumes and extracts
a structured candidate profile using PyMuPDF + Groq LLM.
"""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config.settings import get_settings
from backend.utils.helpers import extract_json_block, truncate
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

RESUME_PARSE_PROMPT = """You are an expert resume parser AI.

Extract all key information from the resume text below and return it as a structured JSON object.

Required fields:
{
  "name": "Full name",
  "email": "email@example.com",
  "phone": "phone number",
  "location": "city, country",
  "summary": "1-2 sentence professional summary",
  "skills": ["skill1", "skill2", ...],
  "experience": [
    {
      "company": "Company name",
      "role": "Job title",
      "duration": "Jan 2023 - Present",
      "description": "Brief description"
    }
  ],
  "education": [
    {
      "institution": "University name",
      "degree": "B.Tech Computer Science",
      "year": "2024",
      "gpa": "8.5 (if mentioned)"
    }
  ],
  "projects": [
    {
      "name": "Project name",
      "tech_stack": ["Python", "FastAPI"],
      "description": "Brief description"
    }
  ],
  "certifications": ["cert1", "cert2"],
  "languages": ["English", "Hindi"],
  "github": "github URL if present",
  "linkedin": "linkedin URL if present",
  "portfolio": "portfolio URL if present"
}

Return ONLY valid JSON. Fill missing fields with empty strings or empty arrays.

Resume text:
"""


class ResumeAgent:
    """
    Parses PDF resumes and extracts a structured candidate profile.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)
        self.llm = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model_primary,
            temperature=0.0,
            max_tokens=3000,
        )

    async def parse(self, pdf_path: str) -> Dict[str, Any]:
        """
        Extract and structure resume data from a PDF file.

        Args:
            pdf_path: Absolute path to the PDF file

        Returns:
            Structured profile dict
        """
        self.log("info", f"📄 Parsing resume: {Path(pdf_path).name}")

        # Step 1: Extract raw text from PDF
        raw_text = self._extract_pdf_text(pdf_path)
        if not raw_text:
            self.log("error", "❌ Could not extract text from PDF")
            return {"error": "Failed to extract text from PDF"}

        self.log("info", f"📝 Extracted {len(raw_text)} characters from PDF")

        # Step 2: Use LLM to parse structured data
        truncated = truncate(raw_text, 5000)
        messages = [
            SystemMessage(content=RESUME_PARSE_PROMPT),
            HumanMessage(content=truncated),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            profile = extract_json_block(response.content)

            if not isinstance(profile, dict):
                # LLM returned non-dict, try regex fallback
                profile = self._regex_fallback(raw_text)

            # Ensure all required fields exist
            profile = self._normalize_profile(profile)
            self.log("success", f"✅ Resume parsed: {profile.get('name', 'Unknown')} | {len(profile.get('skills', []))} skills")
            return profile

        except Exception as exc:
            logger.error(f"Resume LLM parsing failed: {exc}")
            self.log("warn", f"⚠️ LLM parsing failed, using regex fallback: {exc}")
            return self._normalize_profile(self._regex_fallback(raw_text))

    def _extract_pdf_text(self, pdf_path: str) -> str:
        """Extract text from PDF using PyMuPDF."""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            pages_text = []
            for page in doc:
                pages_text.append(page.get_text("text"))
            doc.close()
            return "\n".join(pages_text)
        except Exception as exc:
            logger.error(f"PyMuPDF extraction failed: {exc}")
            return ""

    def _regex_fallback(self, text: str) -> Dict[str, Any]:
        """Basic regex-based extraction when LLM fails."""
        profile: Dict[str, Any] = {}

        # Email
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text)
        profile["email"] = email_match.group(0) if email_match else ""

        # Phone
        phone_match = re.search(r"(\+?\d[\d\s\-().]{8,}\d)", text)
        profile["phone"] = phone_match.group(0).strip() if phone_match else ""

        # Skills — look for common tech terms
        tech_keywords = [
            "Python", "JavaScript", "React", "FastAPI", "Django", "Machine Learning",
            "Deep Learning", "NLP", "LangChain", "Docker", "AWS", "SQL", "MongoDB",
            "TensorFlow", "PyTorch", "RAG", "LLM", "GenAI", "Node.js", "TypeScript",
        ]
        skills_found = [kw for kw in tech_keywords if kw.lower() in text.lower()]
        profile["skills"] = skills_found

        # GitHub / LinkedIn
        github_match = re.search(r"github\.com/[\w-]+", text, re.IGNORECASE)
        profile["github"] = f"https://{github_match.group(0)}" if github_match else ""

        linkedin_match = re.search(r"linkedin\.com/in/[\w-]+", text, re.IGNORECASE)
        profile["linkedin"] = f"https://{linkedin_match.group(0)}" if linkedin_match else ""

        return profile

    def _normalize_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all expected fields exist with default values."""
        defaults = {
            "name": "", "email": "", "phone": "", "location": "",
            "summary": "", "skills": [], "experience": [], "education": [],
            "projects": [], "certifications": [], "languages": [],
            "github": "", "linkedin": "", "portfolio": "",
        }
        for key, default in defaults.items():
            if key not in profile:
                profile[key] = default
        return profile
