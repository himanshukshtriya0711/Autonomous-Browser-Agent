"""
backend/agents/planner_agent.py
================================
Planner Agent — uses Groq LLM to decompose a natural-language user
prompt into a structured, ordered list of executable steps.

Output schema:
{
  "task_type": "job_search" | "web_navigation" | "form_fill" | "pdf_analysis" | "general",
  "steps": [
    {"step": 1, "action": "...", "target": "...", "details": "..."},
    ...
  ],
  "context": {"keywords": [...], "sites": [...], ...}
}
"""

import json
from typing import Any, Callable, Dict, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config.settings import get_settings
from backend.utils.helpers import extract_json_block, utc_now_iso
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

PLANNER_SYSTEM_PROMPT = """You are an expert AI planning agent for an autonomous browser system.

Your job is to break down a user's natural language instruction into a precise, ordered list of browser actions that an AI agent can execute.

Analyse the intent and output a JSON plan. The JSON must follow this exact schema:

{
  "task_type": "<job_search|web_navigation|form_fill|pdf_analysis|data_extraction|general>",
  "steps": [
    {
      "step": 1,
      "action": "<navigate|search|click|extract|fill_form|download_pdf|scroll|wait|analyze>",
      "target": "<URL or element description>",
      "details": "<specific instructions for this step>",
      "expected_outcome": "<what success looks like>"
    }
  ],
  "context": {
    "keywords": ["..."],
    "target_sites": ["..."],
    "data_to_extract": ["..."],
    "priority": "high|medium|low"
  },
  "estimated_steps": <number>
}

Rules:
1. Be specific — describe exactly what to click, search, or extract.
2. For job searches, always include Internshala, Wellfound, and RemoteOK.
3. Break complex tasks into small, atomic steps.
4. Include error recovery steps where needed.
5. Output ONLY valid JSON. No explanation or markdown outside the JSON.
"""


class PlannerAgent:
    """
    Uses the Groq LLM to generate a structured execution plan
    from a natural-language user prompt.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)
        self.llm = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model_primary,
            temperature=0.1,    # Low temp for deterministic planning
            max_tokens=2048,
        )

    async def plan(self, prompt: str) -> Dict[str, Any]:
        """
        Generate an execution plan for the given user prompt.

        Returns a structured dict with task_type, steps, and context.
        Falls back to a default plan if LLM fails.
        """
        self.log("info", f"🧠 Planner analysing: '{prompt}'")

        messages = [
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=f"User instruction: {prompt}"),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            raw_content = response.content

            logger.debug(f"Planner LLM raw response: {raw_content[:500]}")
            plan = extract_json_block(raw_content)

            if not plan or "steps" not in plan:
                raise ValueError("Planner returned invalid JSON structure")

            self.log("info", f"📋 Plan created: {len(plan['steps'])} steps | type: {plan.get('task_type', 'unknown')}")
            logger.info(f"Plan generated: {plan['task_type']} with {len(plan['steps'])} steps")
            return plan

        except Exception as exc:
            logger.error(f"Planner failed: {exc}")
            self.log("warn", f"⚠️ Planner LLM failed, using fallback plan: {exc}")
            return self._fallback_plan(prompt)

    def _fallback_plan(self, prompt: str) -> Dict[str, Any]:
        """Generate a basic fallback plan when LLM is unavailable."""
        prompt_lower = prompt.lower()

        # Detect intent keywords
        if any(kw in prompt_lower for kw in ["job", "intern", "career", "work", "hire"]):
            task_type = "job_search"
            steps = [
                {"step": 1, "action": "navigate", "target": "https://internshala.com", "details": "Open Internshala job portal", "expected_outcome": "Page loaded"},
                {"step": 2, "action": "search", "target": "search box", "details": f"Search for: {prompt}", "expected_outcome": "Results shown"},
                {"step": 3, "action": "extract", "target": "job listings", "details": "Extract job title, company, location, salary, skills", "expected_outcome": "Structured job data"},
            ]
            sites = ["https://internshala.com", "https://wellfound.com", "https://remoteok.com"]
        elif any(kw in prompt_lower for kw in ["pdf", "download", "document"]):
            task_type = "pdf_analysis"
            steps = [
                {"step": 1, "action": "navigate", "target": prompt, "details": "Navigate to target", "expected_outcome": "Page loaded"},
                {"step": 2, "action": "download_pdf", "target": "pdf link", "details": "Download PDF file", "expected_outcome": "PDF saved"},
                {"step": 3, "action": "analyze", "target": "downloaded pdf", "details": "Extract and summarize content", "expected_outcome": "Summary returned"},
            ]
            sites = []
        else:
            task_type = "general"
            steps = [
                {"step": 1, "action": "navigate", "target": "https://www.google.com", "details": f"Search for: {prompt}", "expected_outcome": "Search results"},
                {"step": 2, "action": "extract", "target": "page content", "details": "Extract relevant information", "expected_outcome": "Data extracted"},
            ]
            sites = []

        return {
            "task_type": task_type,
            "steps": steps,
            "context": {
                "keywords": prompt.split()[:5],
                "target_sites": sites,
                "data_to_extract": [],
                "priority": "medium",
            },
            "estimated_steps": len(steps),
        }
