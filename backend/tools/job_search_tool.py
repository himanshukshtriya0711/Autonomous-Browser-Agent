"""
backend/tools/job_search_tool.py
==================================
Job Search Tool — autonomously searches multiple job portals
(Internshala, Wellfound, RemoteOK) and returns structured job listings.

Uses Playwright for browser control + LLM-powered extraction.
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional

from backend.config.settings import get_settings
from backend.services.browser_service import BrowserService
from backend.utils.helpers import clean_text, hash_string, is_valid_url
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# ── Portal search configurations ─────────────────────────────────────────────

JOB_PORTALS = {
    "internshala": {
        "name": "Internshala",
        "search_url": "https://internshala.com/internships/{query}-internship",
        "job_selector": ".individual_internship",
        "title_sel": ".job-internship-name",
        "company_sel": ".company-name",
        "location_sel": ".location_link",
        "salary_sel": ".stipend",
        "skills_sel": ".round_tabs",
        "link_attr": "href",
        "base_url": "https://internshala.com",
    },
    "remoteok": {
        "name": "RemoteOK",
        "search_url": "https://remoteok.com/remote-{query}-jobs",
        "job_selector": "tr.job",
        "title_sel": "h2[itemprop='title']",
        "company_sel": "h3[itemprop='name']",
        "location_sel": ".location",
        "salary_sel": ".salary",
        "skills_sel": ".tag",
        "link_attr": "data-href",
        "base_url": "https://remoteok.com",
    },
    "wellfound": {
        "name": "Wellfound (AngelList)",
        "search_url": "https://wellfound.com/jobs?q={query}&remote=true",
        "job_selector": "[data-test='JobListing']",
        "title_sel": "[data-test='JobListing-title']",
        "company_sel": "[data-test='JobListing-company']",
        "location_sel": "[data-test='JobListing-location']",
        "salary_sel": "[data-test='JobListing-compensation']",
        "skills_sel": ".tag",
        "link_attr": "href",
        "base_url": "https://wellfound.com",
    },
    "linkedin": {
    "name": "LinkedIn",
    "search_url": "https://www.linkedin.com/jobs/search/?keywords={query}&f_WT=2",
    "job_selector": ".base-card",
    "title_sel": ".base-search-card__title",
    "company_sel": ".base-search-card__subtitle",
    "location_sel": ".job-search-card__location",
    "salary_sel": ".job-search-card__salary-info",
    "skills_sel": ".job-criteria__text",
    "link_attr": "href",
    "base_url": "https://www.linkedin.com",
    },

    "indeed": {
        "name": "Indeed",
        "search_url": "https://in.indeed.com/jobs?q={query}&l=Remote",
        "job_selector": ".job_seen_beacon",
        "title_sel": '[data-testid="job-title"]',
        "company_sel": '[data-testid="company-name"]',
        "location_sel": '[data-testid="text-location"]',
        "salary_sel": ".salary-snippet",
        "skills_sel": ".js-match-insights-provider-tvvxwd",
        "link_attr": "href",
        "base_url": "https://in.indeed.com",
    },

    "naukri": {
        "name": "Naukri",
        "search_url": "https://www.naukri.com/{query}-jobs",
        "job_selector": ".srp-jobtuple-wrapper",
        "title_sel": ".title",
        "company_sel": ".comp-name",
        "location_sel": ".locWdth",
        "salary_sel": ".sal-wrap",
        "skills_sel": ".tags-gt li",
        "link_attr": "href",
        "base_url": "https://www.naukri.com",
    },
}


class JobSearchTool:
    """
    Autonomous job search tool that scrapes multiple portals.
    Returns structured, deduplicated job listings.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)
        self._seen_hashes: set = set()

    async def search(
        self,
        query: str,
        sites: Optional[List[str]] = None,
        headless: bool = False,
        max_results: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Search for jobs across multiple portals concurrently.

        Args:
            query: Search keywords (e.g. "GenAI intern", "Python backend")
            sites: List of portal URLs to search (defaults to all portals)
            headless: Run browser headlessly
            max_results: Maximum total jobs to return

        Returns:
            List of structured job dicts
        """
        self.log("info", f"🔍 Searching jobs: '{query}' across portals…")
        all_jobs: List[Dict[str, Any]] = []

        # Determine which portals to search
        portals_to_search = []
        if sites:
            for site in sites:
                for key, config in JOB_PORTALS.items():
                    if key in site.lower() or config["base_url"] in site:
                        portals_to_search.append(config)
        if not portals_to_search:
            portals_to_search = list(JOB_PORTALS.values())

        # Search each portal sequentially (avoids browser instance conflicts)
        for portal in portals_to_search:
            if len(all_jobs) >= max_results:
                break
            try:
                self.log("info", f"📡 Searching {portal['name']}…")
                jobs = await self._search_portal(portal, query, headless)
                all_jobs.extend(jobs)
                self.log("success", f"✅ {portal['name']}: {len(jobs)} jobs found")
                # Small delay between portals to be respectful
                await asyncio.sleep(2)
            except Exception as exc:
                self.log("warn", f"⚠️ {portal['name']} failed: {exc}")
                logger.error(f"Portal search failed ({portal['name']}): {exc}")

        # Also do a Google/DuckDuckGo fallback if very few results
        if len(all_jobs) < 5:
            self.log("info", "🔎 Trying general web search for jobs…")
            fallback_jobs = await self._google_search_jobs(query, headless)
            all_jobs.extend(fallback_jobs)

        self.log("success", f"🎯 Total: {len(all_jobs)} jobs found across all portals")
        return all_jobs[:max_results]

    async def _search_portal(
        self,
        portal: Dict[str, Any],
        query: str,
        headless: bool,
    ) -> List[Dict[str, Any]]:
        """Scrape a single job portal for listings."""
        query_slug = query.lower().replace(" ", "-")
        search_url = portal["search_url"].format(query=query_slug)

        jobs = []
        async with BrowserService(headless=headless) as browser:
            page = await browser.new_page()
            try:
                # Navigate to portal
                await page.goto(search_url, wait_until="domcontentloaded", timeout=settings.browser_timeout)
                await BrowserService.human_delay(1500, 3000)
                await BrowserService.dismiss_popups(page)

                # Scroll to load more listings
                await BrowserService.scroll_to_bottom(page, steps=3)
                await BrowserService.human_delay(1000, 2000)

                # Try structured extraction first
                job_elements = await page.query_selector_all(portal["job_selector"])

                if job_elements:
                    for element in job_elements[:15]:  # Limit per portal
                        job = await self._extract_job_from_element(element, portal)
                        if job:
                            # Dedup
                            key = hash_string(f"{job['company']}{job['role']}")
                            if key not in self._seen_hashes:
                                self._seen_hashes.add(key)
                                jobs.append(job)
                else:
                    # Fallback: extract page text and use LLM
                    self.log("info", f"⚡ Falling back to text extraction for {portal['name']}")
                    text = await BrowserService.get_page_text(page)
                    jobs = await self._extract_jobs_from_text(text, search_url)

            except Exception as exc:
                logger.error(f"Portal scrape failed: {exc}")
            finally:
                await page.close()

        return jobs

    async def _extract_job_from_element(
        self,
        element: Any,
        portal: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Extract job data from a DOM element."""
        try:
            async def safe_text(sel: str) -> str:
                try:
                    el = await element.query_selector(sel)
                    return clean_text(await el.inner_text()) if el else ""
                except Exception:
                    return ""

            async def safe_texts(sel: str) -> List[str]:
                try:
                    els = await element.query_selector_all(sel)
                    texts = []
                    for el in els[:8]:
                        t = clean_text(await el.inner_text())
                        if t:
                            texts.append(t)
                    return texts
                except Exception:
                    return []

            title    = await safe_text(portal["title_sel"])
            company  = await safe_text(portal["company_sel"])
            location = await safe_text(portal["location_sel"])
            salary   = await safe_text(portal["salary_sel"])
            skills   = await safe_texts(portal["skills_sel"])

            # Get apply link
            apply_link = ""
            try:
                href = await element.get_attribute(portal["link_attr"])
                if href:
                    if href.startswith("http"):
                        apply_link = href
                    elif href.startswith("/"):
                        apply_link = portal["base_url"] + href
            except Exception:
                pass

            if not title and not company:
                return None

            return {
                "company": company or "Unknown",
                "role": title or "Unknown Role",
                "location": location or "Not specified",
                "salary": salary or "Not specified",
                "skills": skills,
                "apply_link": apply_link,
                "source": portal["name"],
                "source_url": portal["base_url"],
            }

        except Exception as exc:
            logger.debug(f"Element extraction failed: {exc}")
            return None

    async def _extract_jobs_from_text(
        self,
        text: str,
        source_url: str,
    ) -> List[Dict[str, Any]]:
        """Fallback: use LLM to extract jobs from raw page text."""
        try:
            from backend.agents.extraction_agent import ExtractionAgent
            extractor = ExtractionAgent(log_callback=self.log)
            return await extractor.extract_jobs(text, source_url)
        except Exception as exc:
            logger.error(f"Text-based extraction failed: {exc}")
            return []

    async def _google_search_jobs(self, query: str, headless: bool) -> List[Dict[str, Any]]:
        """Search Google for job listings as a fallback."""
        search_query = f"{query} internship OR job site:internshala.com OR site:wellfound.com OR site:remoteok.com"
        jobs = []

        async with BrowserService(headless=headless) as browser:
            page = await browser.new_page()
            try:
                await page.goto("https://www.google.com", wait_until="domcontentloaded")
                await BrowserService.human_delay()
                await BrowserService.safe_fill(page, 'textarea[name="q"]', search_query)
                await page.keyboard.press("Enter")
                await BrowserService.human_delay(2000, 3000)

                text = await BrowserService.get_page_text(page)
                jobs = await self._extract_jobs_from_text(text, "https://google.com")
            except Exception as exc:
                logger.error(f"Google fallback search failed: {exc}")
            finally:
                await page.close()

        return jobs
