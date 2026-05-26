"""
backend/tools/form_fill_tool.py
=================================
Form Fill Tool — automatically detects form fields on a page
and fills them with data from a resume profile or provided values.

Supports:
- Text inputs, textareas
- Select dropdowns
- Checkboxes
- File uploads (resume)
"""

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.config.settings import get_settings
from backend.services.browser_service import BrowserService
from backend.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class FormFillTool:
    """
    Autonomous form detection and filling tool.
    Uses intelligent field matching to map profile data to form inputs.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)

    async def fill_application_form(
        self,
        url: str,
        profile: Dict[str, Any],
        resume_path: Optional[str] = None,
        headless: bool = False,
    ) -> Dict[str, Any]:
        """
        Navigate to a form URL and fill it with profile data.

        Args:
            url: Form URL
            profile: Candidate profile dict (from resume agent)
            resume_path: Optional path to PDF resume for file upload
            headless: Run browser headlessly

        Returns:
            Dict with filled field count, success status
        """
        self.log("info", f"📝 Filling form at: {url}")

        async with BrowserService(headless=headless) as browser:
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout)
                await BrowserService.human_delay(1000, 2000)
                await BrowserService.dismiss_popups(page)

                # Detect all form fields
                fields = await self._detect_form_fields(page)
                self.log("info", f"🔎 Detected {len(fields)} form fields")

                filled_count = 0
                for field in fields:
                    success = await self._fill_field(page, field, profile)
                    if success:
                        filled_count += 1
                    await BrowserService.human_delay(200, 500)

                # Handle file upload if resume path provided
                if resume_path and Path(resume_path).exists():
                    uploaded = await self._upload_file(page, resume_path)
                    self.log("info", f"📎 Resume upload: {'success' if uploaded else 'failed'}")

                self.log("success", f"✅ Filled {filled_count}/{len(fields)} fields")
                return {
                    "success": True,
                    "url": url,
                    "fields_detected": len(fields),
                    "fields_filled": filled_count,
                    "submitted": False,  # Don't auto-submit — safety measure
                }

            except Exception as exc:
                self.log("error", f"❌ Form fill failed: {exc}")
                return {"success": False, "url": url, "error": str(exc)}
            finally:
                await page.close()

    async def _detect_form_fields(self, page: Any) -> List[Dict[str, Any]]:
        """Detect all fillable form fields on the page."""
        try:
            fields = await page.evaluate("""
                () => {
                    const fields = [];
                    const inputs = document.querySelectorAll(
                        'input[type="text"], input[type="email"], input[type="tel"], ' +
                        'input[type="url"], input[type="number"], textarea, select'
                    );
                    inputs.forEach((el, idx) => {
                        const label = document.querySelector(`label[for="${el.id}"]`);
                        fields.push({
                            index: idx,
                            tag: el.tagName.toLowerCase(),
                            type: el.type || el.tagName.toLowerCase(),
                            id: el.id || '',
                            name: el.name || '',
                            placeholder: el.placeholder || '',
                            label: label ? label.innerText.trim() : '',
                            selector: el.id ? `#${el.id}` : (el.name ? `[name="${el.name}"]` : null)
                        });
                    });
                    return fields;
                }
            """)
            return [f for f in fields if f.get("selector")]
        except Exception as exc:
            logger.error(f"Field detection failed: {exc}")
            return []

    async def _fill_field(
        self,
        page: Any,
        field: Dict[str, Any],
        profile: Dict[str, Any],
    ) -> bool:
        """Map a form field to the best profile value and fill it."""
        selector = field.get("selector", "")
        if not selector:
            return False

        # Determine what value to fill based on field metadata
        value = self._match_field_to_profile(field, profile)
        if not value:
            return False

        try:
            field_type = field.get("type", "text")

            if field_type == "select":
                # Try to select matching option
                options = await page.evaluate(
                    f"Array.from(document.querySelector('{selector}').options).map(o => o.text)"
                )
                best_option = self._find_best_option(value, options)
                if best_option:
                    await page.select_option(selector, label=best_option)
                    return True
            else:
                return await BrowserService.safe_fill(page, selector, str(value))
        except Exception as exc:
            logger.debug(f"Failed to fill field {selector}: {exc}")
            return False

    def _match_field_to_profile(
        self,
        field: Dict[str, Any],
        profile: Dict[str, Any],
    ) -> Optional[str]:
        """Fuzzy-match a form field to the best profile value."""
        # Combine all field hints for matching
        hints = " ".join([
            field.get("label", ""),
            field.get("name", ""),
            field.get("id", ""),
            field.get("placeholder", ""),
        ]).lower()

        # Name
        if any(kw in hints for kw in ["name", "full name", "candidate"]):
            return profile.get("name", "")

        # Email
        if "email" in hints or "mail" in hints:
            return profile.get("email", "")

        # Phone
        if any(kw in hints for kw in ["phone", "mobile", "contact", "tel"]):
            return profile.get("phone", "")

        # Location / City
        if any(kw in hints for kw in ["city", "location", "address", "place"]):
            return profile.get("location", "")

        # LinkedIn
        if "linkedin" in hints:
            return profile.get("linkedin", "")

        # GitHub / Portfolio
        if any(kw in hints for kw in ["github", "portfolio", "website"]):
            return profile.get("github", "") or profile.get("portfolio", "")

        # Cover letter / Summary / About
        if any(kw in hints for kw in ["cover", "letter", "about", "summary", "introduce", "motivation"]):
            skills_str = ", ".join(profile.get("skills", [])[:5])
            name = profile.get("name", "I")
            return (
                f"I am {name}, a passionate developer with expertise in {skills_str}. "
                f"{profile.get('summary', 'I am eager to contribute to your team.')}"
            )

        # Skills
        if "skill" in hints:
            return ", ".join(profile.get("skills", []))

        return None

    def _find_best_option(self, value: str, options: List[str]) -> Optional[str]:
        """Find the best matching dropdown option for a value."""
        value_lower = value.lower()
        for option in options:
            if value_lower in option.lower():
                return option
        return None

    async def _upload_file(self, page: Any, file_path: str) -> bool:
        """Upload a file using a file input element."""
        try:
            file_input = await page.query_selector('input[type="file"]')
            if file_input:
                await file_input.set_input_files(file_path)
                await BrowserService.human_delay(500, 1000)
                return True
        except Exception as exc:
            logger.debug(f"File upload failed: {exc}")
        return False
