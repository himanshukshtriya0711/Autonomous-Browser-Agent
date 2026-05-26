"""
backend/tools/web_nav_tool.py
================================
Web Navigation Tool — generic, reusable browser navigation actions.

Provides a high-level API for common navigation tasks:
- goto: Navigate to a URL
- search_on_page: Find search input and submit query
- click_element: Click a specific element
- extract_links: Extract all links from a page
- screenshot: Take a screenshot (for debugging)
- wait_and_get: Wait for element and return its text
"""

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.config.settings import get_settings
from backend.services.browser_service import BrowserService
from backend.utils.helpers import is_valid_url, utc_now_iso
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class WebNavTool:
    """Generic web navigation tool for autonomous browser control."""

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)

    async def navigate_and_extract(
        self,
        url: str,
        extract_jobs: bool = False,
        headless: bool = False,
    ) -> Dict[str, Any]:
        """
        Navigate to a URL, optionally scroll and extract content.
        Returns page text and metadata.
        """
        if not is_valid_url(url):
            return {"error": f"Invalid URL: {url}", "content": "", "url": url}

        self.log("info", f"🔗 Navigating to: {url}")
        async with BrowserService(headless=headless) as browser:
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout)
                await BrowserService.human_delay(1000, 2000)
                await BrowserService.dismiss_popups(page)
                await BrowserService.scroll_to_bottom(page, steps=3)
                await BrowserService.human_delay(500, 1000)

                text    = await BrowserService.get_page_text(page)
                title   = await page.title()
                cur_url = page.url
                links   = await self._extract_links(page)

                self.log("success", f"✅ Page loaded: {title[:60]}")
                return {
                    "url": cur_url,
                    "title": title,
                    "content": text[:6000],
                    "links": links[:20],
                    "success": True,
                }
            except Exception as exc:
                self.log("error", f"❌ Navigation failed: {exc}")
                return {"error": str(exc), "url": url, "success": False}
            finally:
                await page.close()

    async def search_and_extract(
        self,
        base_url: str,
        query: str,
        headless: bool = False,
    ) -> Dict[str, Any]:
        """Navigate to a site, perform search, and return results page content."""
        self.log("info", f"🔍 Searching '{query}' on {base_url}")
        async with BrowserService(headless=headless) as browser:
            page = await browser.new_page()
            try:
                await page.goto(base_url, wait_until="domcontentloaded", timeout=settings.browser_timeout)
                await BrowserService.human_delay()
                await BrowserService.dismiss_popups(page)

                # Try various search input selectors
                search_selectors = [
                    'input[type="search"]', 'input[name="q"]', 'input[name="query"]',
                    'input[placeholder*="search" i]', 'input[placeholder*="Search" i]',
                    '#search-input', '#searchbox', '.search-input',
                    'input[type="text"]',
                ]

                searched = False
                for selector in search_selectors:
                    if await BrowserService.safe_fill(page, selector, query):
                        await page.keyboard.press("Enter")
                        await BrowserService.human_delay(2000, 3500)
                        searched = True
                        break

                if not searched:
                    self.log("warn", "⚠️ No search input found, extracting page as-is")

                await BrowserService.scroll_to_bottom(page, steps=3)
                text  = await BrowserService.get_page_text(page)
                title = await page.title()

                return {
                    "url": page.url,
                    "title": title,
                    "content": text[:6000],
                    "searched": searched,
                    "success": True,
                }
            except Exception as exc:
                self.log("error", f"❌ Search failed: {exc}")
                return {"error": str(exc), "success": False}
            finally:
                await page.close()

    async def click_and_extract(
        self,
        url: str,
        selector: str,
        headless: bool = False,
    ) -> Dict[str, Any]:
        """Navigate to URL, click an element, return resulting page content."""
        async with BrowserService(headless=headless) as browser:
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout)
                await BrowserService.human_delay()

                clicked = await BrowserService.safe_click(page, selector)
                if clicked:
                    await BrowserService.human_delay(1500, 2500)
                    text = await BrowserService.get_page_text(page)
                    return {"success": True, "clicked": True, "content": text[:4000], "url": page.url}
                else:
                    return {"success": False, "clicked": False, "error": f"Selector not found: {selector}"}
            except Exception as exc:
                return {"success": False, "error": str(exc)}
            finally:
                await page.close()

    async def multi_page_extract(
        self,
        urls: List[str],
        headless: bool = False,
    ) -> List[Dict[str, Any]]:
        """Extract content from multiple URLs sequentially."""
        results = []
        for url in urls:
            result = await self.navigate_and_extract(url, headless=headless)
            results.append(result)
            await asyncio.sleep(1.5)  # Polite delay
        return results

    async def _extract_links(self, page: Any) -> List[Dict[str, str]]:
        """Extract all hyperlinks from the current page."""
        try:
            links = await page.evaluate("""
                () => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => ({ text: a.innerText.trim().slice(0, 100), href: a.href }))
                        .filter(l => l.href.startsWith('http') && l.text.length > 0);
                }
            """)
            return links
        except Exception:
            return []
