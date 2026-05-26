"""
backend/services/browser_service.py
=====================================
Playwright browser lifecycle management.

Manages a shared Playwright instance across tasks.
Provides helper methods for common browser operations with
built-in retry logic, human-like delays, and error recovery.
"""

import asyncio
import random
from contextlib import asynccontextmanager
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from backend.config.settings import get_settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class BrowserService:
    """
    Manages a Playwright browser instance.
    Use as an async context manager for automatic cleanup.
    """

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def start(self) -> "BrowserService":
        """Launch browser and create a default context."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=settings.browser_slow_mo,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            java_script_enabled=True,
        )
        # Mask automation signals
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.info(f"Browser launched (headless={self.headless})")
        return self

    async def stop(self) -> None:
        """Close browser and playwright."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info("Browser stopped cleanly")
        except Exception as exc:
            logger.warning(f"Error during browser shutdown: {exc}")

    async def new_page(self) -> Page:
        """Open a new browser tab."""
        if not self._context:
            raise RuntimeError("Browser not started. Call .start() first.")
        page = await self._context.new_page()
        page.set_default_timeout(settings.browser_timeout)
        return page

    @asynccontextmanager
    async def page_context(self):
        """Context manager that opens and auto-closes a page."""
        page = await self.new_page()
        try:
            yield page
        finally:
            await page.close()

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *_):
        await self.stop()

    # ── Human-like interaction helpers ────────────────────────────────────────

    @staticmethod
    async def human_delay(min_ms: int = 300, max_ms: int = 900) -> None:
        """Pause for a random duration to simulate human behaviour."""
        delay = random.randint(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    @staticmethod
    async def safe_click(page: Page, selector: str, timeout: int = 10_000) -> bool:
        """Click an element safely, returning False if not found."""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            await page.click(selector)
            await BrowserService.human_delay()
            return True
        except Exception as exc:
            logger.debug(f"safe_click failed for '{selector}': {exc}")
            return False

    @staticmethod
    async def safe_fill(page: Page, selector: str, value: str, timeout: int = 10_000) -> bool:
        """Fill an input element safely."""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            await page.fill(selector, "")       # Clear first
            await BrowserService.human_delay(100, 300)
            await page.fill(selector, value)
            await BrowserService.human_delay()
            return True
        except Exception as exc:
            logger.debug(f"safe_fill failed for '{selector}': {exc}")
            return False

    @staticmethod
    async def scroll_to_bottom(page: Page, steps: int = 5) -> None:
        """Gradually scroll to the bottom of the page."""
        for _ in range(steps):
            await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
            await asyncio.sleep(0.4)

    @staticmethod
    async def wait_for_navigation(page: Page, url_fragment: str = "", timeout: int = 30_000) -> bool:
        """Wait for page navigation to complete."""
        try:
            if url_fragment:
                await page.wait_for_url(f"**{url_fragment}**", timeout=timeout)
            else:
                await page.wait_for_load_state("networkidle", timeout=timeout)
            return True
        except Exception as exc:
            logger.debug(f"Navigation wait failed: {exc}")
            return False

    @staticmethod
    async def get_page_text(page: Page) -> str:
        """Extract all visible text from the page."""
        try:
            return await page.evaluate("""
                () => {
                    const elements = document.querySelectorAll('p, h1, h2, h3, h4, li, td, span, div');
                    return Array.from(elements)
                        .map(el => el.innerText)
                        .filter(t => t && t.trim().length > 0)
                        .join('\\n');
                }
            """)
        except Exception:
            return await page.inner_text("body") if await page.query_selector("body") else ""

    @staticmethod
    async def dismiss_popups(page: Page) -> None:
        """Attempt to dismiss common popups and cookie banners."""
        dismiss_selectors = [
            "button[aria-label*='close']",
            "button[aria-label*='Close']",
            "button[aria-label*='dismiss']",
            ".cookie-accept", "#cookie-accept",
            "button:has-text('Accept')",
            "button:has-text('Got it')",
            "button:has-text('I agree')",
            "[data-testid='close-button']",
        ]
        for sel in dismiss_selectors:
            try:
                if await page.query_selector(sel):
                    await page.click(sel)
                    await BrowserService.human_delay(200, 500)
                    logger.debug(f"Dismissed popup: {sel}")
                    break
            except Exception:
                continue
