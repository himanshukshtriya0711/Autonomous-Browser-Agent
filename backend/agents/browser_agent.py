"""
backend/agents/browser_agent.py
=================================
Browser Agent — wraps browser-use's Agent with Playwright control.

This agent receives a task description and a browser page, then uses
the Groq LLM to decide browser actions step by step using browser-use's
built-in action loop.

Falls back to direct Playwright control when browser-use is unavailable.
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional

from backend.config.settings import get_settings
from backend.services.browser_service import BrowserService
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class BrowserAgent:
    """
    Autonomous browser agent that combines browser-use + Playwright.

    For each step in the plan, this agent:
    1. Receives the action and target from the planner
    2. Opens/navigates the browser
    3. Uses LLM reasoning to decide exact interactions
    4. Executes them via Playwright
    5. Returns the result
    """

    def __init__(
        self,
        log_callback: Optional[Callable[[str, str], None]] = None,
        headless: bool = False,
    ):
        self.log = log_callback or (lambda level, msg: None)
        self.headless = headless
        self.browser_service: Optional[BrowserService] = None
        self._use_browser_use = self._check_browser_use()

    def _check_browser_use(self) -> bool:
        """Check if browser-use package is available."""
        try:
            import browser_use  # noqa: F401
            return True
        except ImportError:
            logger.warning("browser-use not available, using direct Playwright control")
            return False

    async def execute_with_browser_use(
        self,
        task: str,
        max_steps: int = 20,
    ) -> Dict[str, Any]:
        """
        Execute task using browser-use Agent (full autonomous loop).
        Uses Groq LLM as the reasoning model.
        """
        try:
            from browser_use import Agent
            from langchain_groq import ChatGroq

            self.log("info", "🌐 Initialising browser-use autonomous agent…")

            llm = ChatGroq(
                api_key=settings.groq_api_key,
                model=settings.groq_model_primary,
                temperature=0.0,
            )

            agent = Agent(
                task=task,
                llm=llm,
                max_steps=max_steps,
                headless=self.headless,
                use_vision=False,   # Text-based for speed
            )

            self.log("info", f"▶️ Running browser-use agent: {task[:80]}")
            result = await agent.run()

            extracted = {
                "success": True,
                "method": "browser-use",
                "task": task,
                "result": str(result) if result else "Completed",
                "steps_completed": max_steps,
            }
            self.log("success", "✅ browser-use agent completed task")
            return extracted

        except Exception as exc:
            logger.error(f"browser-use agent failed: {exc}")
            self.log("warn", f"⚠️ browser-use failed: {exc}. Falling back to Playwright…")
            return await self.execute_with_playwright(task)

    async def execute_with_playwright(
        self,
        task: str,
        url: Optional[str] = None,
        actions: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Execute browser actions directly with Playwright.
        Used as fallback or for specific tool actions.
        """
        self.log("info", f"🎭 Starting Playwright browser for: {task[:60]}")
        results = []

        async with BrowserService(headless=self.headless) as browser:
            page = await browser.new_page()

            try:
                if url:
                    self.log("info", f"🔗 Navigating to: {url}")
                    await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout)
                    await BrowserService.human_delay(500, 1200)
                    await BrowserService.dismiss_popups(page)

                if actions:
                    for action_def in actions:
                        result = await self._execute_action(page, action_def, browser)
                        results.append(result)
                else:
                    # Default: extract page content
                    text = await BrowserService.get_page_text(page)
                    results.append({"action": "extract_text", "content": text[:3000]})

                return {
                    "success": True,
                    "method": "playwright",
                    "task": task,
                    "results": results,
                    "steps_completed": len(results),
                }

            except Exception as exc:
                logger.error(f"Playwright execution failed: {exc}")
                self.log("error", f"❌ Browser error: {exc}")
                return {
                    "success": False,
                    "method": "playwright",
                    "task": task,
                    "error": str(exc),
                    "results": results,
                    "steps_completed": len(results),
                }

    async def _execute_action(
        self,
        page: Any,
        action_def: Dict[str, Any],
        browser: BrowserService,
    ) -> Dict[str, Any]:
        """Execute a single browser action from a plan step."""
        action = action_def.get("action", "")
        target = action_def.get("target", "")
        details = action_def.get("details", "")

        self.log("info", f"⚙️ Action: {action} | Target: {target[:50]}")

        try:
            if action == "navigate":
                url = target if target.startswith("http") else f"https://{target}"
                await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout)
                await BrowserService.human_delay()
                await BrowserService.dismiss_popups(page)
                return {"action": action, "target": url, "status": "success"}

            elif action == "search":
                selectors = [
                    'input[type="search"]', 'input[name="q"]',
                    'input[placeholder*="search" i]', 'input[placeholder*="Search" i]',
                    '#search', '.search-input', '[data-testid*="search"]',
                ]
                for sel in selectors:
                    if await BrowserService.safe_fill(page, sel, details or target):
                        await page.keyboard.press("Enter")
                        await BrowserService.human_delay(1000, 2000)
                        break
                text = await BrowserService.get_page_text(page)
                return {"action": action, "query": details or target, "status": "success", "content": text[:2000]}

            elif action == "click":
                clicked = await BrowserService.safe_click(page, target)
                await BrowserService.human_delay()
                return {"action": action, "target": target, "status": "success" if clicked else "not_found"}

            elif action == "scroll":
                await BrowserService.scroll_to_bottom(page)
                return {"action": action, "status": "success"}

            elif action == "extract":
                text = await BrowserService.get_page_text(page)
                current_url = page.url
                return {
                    "action": action,
                    "url": current_url,
                    "content": text[:4000],
                    "status": "success",
                }

            elif action == "wait":
                await asyncio.sleep(2)
                return {"action": action, "status": "success"}

            else:
                # Generic: try to extract page content
                text = await BrowserService.get_page_text(page)
                return {"action": action, "content": text[:2000], "status": "completed"}

        except Exception as exc:
            logger.debug(f"Action {action} failed: {exc}")
            return {"action": action, "target": target, "status": "failed", "error": str(exc)}

    async def run(
        self,
        task: str,
        plan_steps: Optional[List[Dict]] = None,
        max_steps: int = 20,
    ) -> Dict[str, Any]:
        """
        Main entry point — choose execution method based on availability and task.
        """
        if self._use_browser_use and not plan_steps:
            # Let browser-use handle the full autonomous loop
            return await self.execute_with_browser_use(task, max_steps)
        else:
            # Use direct Playwright with plan steps
            url = None
            actions = plan_steps or []
            # Extract first navigation URL if present
            if actions and actions[0].get("action") == "navigate":
                url = actions[0]["target"]
                actions = actions[1:]

            return await self.execute_with_playwright(task, url=url, actions=actions)
