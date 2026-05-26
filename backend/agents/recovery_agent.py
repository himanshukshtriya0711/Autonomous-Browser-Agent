"""
backend/agents/recovery_agent.py
==================================
Recovery Agent — analyses failures and decides the best retry strategy.

When a step fails, this agent:
1. Analyses the error type and context
2. Decides whether to retry, skip, or adapt
3. Suggests an alternative action
4. Tracks failure history to avoid infinite loops
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config.settings import get_settings
from backend.utils.helpers import extract_json_block
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

RECOVERY_PROMPT = """You are an AI recovery agent for an autonomous browser system.

A browser action has failed. Analyse the error and decide the best recovery strategy.

Return a JSON object with this schema:
{
  "strategy": "retry" | "skip" | "alternative" | "abort",
  "reason": "Brief explanation",
  "alternative_action": {
    "action": "navigate|search|click|extract|wait",
    "target": "...",
    "details": "..."
  },
  "wait_seconds": 2,
  "confidence": 0.8
}

Rules:
- "retry": Same action, try again (for timeouts, network errors)
- "skip": Skip this step, continue to next (for non-critical steps)
- "alternative": Try a different approach (element not found, page changed)
- "abort": Stop the task (unrecoverable error)
- Set wait_seconds > 0 for rate limiting or page loading issues
"""


class RecoveryAgent:
    """
    Intelligently handles failures in the browser agent pipeline.
    Uses exponential backoff and LLM-driven strategy selection.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)
        self.llm = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model_primary,
            temperature=0.1,
            max_tokens=512,
        )
        # Track failures per step to prevent infinite retry loops
        self._failure_counts: Dict[str, int] = {}

    async def analyze_and_recover(
        self,
        failed_step: Dict[str, Any],
        error: str,
        context: str = "",
    ) -> Dict[str, Any]:
        """
        Analyse a failure and recommend a recovery action.

        Args:
            failed_step: The step dict that failed
            error: The error message
            context: Additional context about what was happening

        Returns:
            Recovery strategy dict
        """
        step_key = f"{failed_step.get('action', '')}_{failed_step.get('target', '')[:30]}"
        self._failure_counts[step_key] = self._failure_counts.get(step_key, 0) + 1
        failure_count = self._failure_counts[step_key]

        self.log("warn", f"🔧 Recovery agent: analysing failure (attempt {failure_count}) — {error[:100]}")

        # Hard abort if too many failures on same step
        if failure_count >= settings.max_retries:
            self.log("error", f"❌ Max retries reached for step: {step_key}")
            return {"strategy": "skip", "reason": f"Max retries ({settings.max_retries}) exceeded", "wait_seconds": 0}

        # Fast-path for common errors (no LLM needed)
        fast_strategy = self._fast_classify(error, failure_count)
        if fast_strategy:
            self.log("info", f"⚡ Fast recovery: {fast_strategy['strategy']} — {fast_strategy['reason']}")
            return fast_strategy

        # Use LLM for complex failure analysis
        try:
            context_text = f"""
Failed step: {failed_step}
Error: {error}
Context: {context}
Attempt number: {failure_count}
"""
            messages = [
                SystemMessage(content=RECOVERY_PROMPT),
                HumanMessage(content=context_text),
            ]
            response = await self.llm.ainvoke(messages)
            strategy = extract_json_block(response.content)

            if isinstance(strategy, dict) and "strategy" in strategy:
                self.log("info", f"🧠 LLM recovery strategy: {strategy['strategy']} — {strategy.get('reason', '')}")
                return strategy

        except Exception as exc:
            logger.error(f"Recovery LLM failed: {exc}")

        # Default fallback
        return {"strategy": "retry", "reason": "Default retry", "wait_seconds": 2 * failure_count}

    def _fast_classify(self, error: str, attempt: int) -> Optional[Dict[str, Any]]:
        """Quickly classify common errors without calling the LLM."""
        error_lower = error.lower()

        if any(kw in error_lower for kw in ["timeout", "timed out", "time out"]):
            return {
                "strategy": "retry",
                "reason": "Timeout — page may still be loading",
                "wait_seconds": min(5 * attempt, 30),
                "alternative_action": None,
            }

        if any(kw in error_lower for kw in ["net::err", "navigation", "net_error"]):
            return {
                "strategy": "retry",
                "reason": "Network error — retrying with delay",
                "wait_seconds": 5,
                "alternative_action": None,
            }

        if any(kw in error_lower for kw in ["element not found", "no such element", "not visible"]):
            return {
                "strategy": "alternative",
                "reason": "Element not found — try alternative selector",
                "wait_seconds": 1,
                "alternative_action": {
                    "action": "wait",
                    "target": "page",
                    "details": "Wait for dynamic content to load",
                },
            }

        if any(kw in error_lower for kw in ["rate limit", "429", "too many requests"]):
            return {
                "strategy": "retry",
                "reason": "Rate limited — backing off",
                "wait_seconds": 30,
                "alternative_action": None,
            }

        if any(kw in error_lower for kw in ["403", "forbidden", "access denied"]):
            return {
                "strategy": "skip",
                "reason": "Access denied — skipping this source",
                "wait_seconds": 0,
                "alternative_action": None,
            }

        return None

    async def execute_with_retry(
        self,
        func: Callable,
        step: Dict[str, Any],
        *args,
        **kwargs,
    ) -> Tuple[Any, bool]:
        """
        Wrap an async function call with automatic retry + recovery logic.

        Returns (result, success) tuple.
        """
        for attempt in range(1, settings.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                return result, True
            except Exception as exc:
                error_msg = str(exc)
                self.log("warn", f"⚠️ Attempt {attempt}/{settings.max_retries} failed: {error_msg[:80]}")

                recovery = await self.analyze_and_recover(step, error_msg)

                if recovery["strategy"] == "abort":
                    self.log("error", "🛑 Aborting — unrecoverable error")
                    return None, False

                if recovery["strategy"] == "skip":
                    self.log("warn", "⏭️ Skipping failed step")
                    return None, False

                wait_time = recovery.get("wait_seconds", 2)
                if wait_time > 0:
                    self.log("info", f"⏳ Waiting {wait_time}s before retry…")
                    await asyncio.sleep(wait_time)

        return None, False

    def reset(self) -> None:
        """Reset failure counts for a new task."""
        self._failure_counts.clear()
