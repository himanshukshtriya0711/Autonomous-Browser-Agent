"""
backend/utils/helpers.py
=========================
Shared utility functions used across agents, tools, and services.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any


# ── ID & timestamp helpers ────────────────────────────────────────────────────

def generate_task_id() -> str:
    """Generate a unique task ID."""
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def hash_string(text: str) -> str:
    """Return SHA-256 hex digest of a string (for deduplication)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── JSON helpers ──────────────────────────────────────────────────────────────

def safe_json_loads(raw: str, default: Any = None) -> Any:
    """Parse JSON string safely; return default on failure."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def extract_json_block(text: str) -> Any:
    """
    Extract the first JSON object or array from a larger text block.
    Used when the LLM wraps JSON in markdown code fences.
    """
    # Try to find ```json ... ``` fenced block
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if fence_match:
        return safe_json_loads(fence_match.group(1).strip())

    # Fallback: find first { or [ and extract balanced block
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue
        depth = 0
        for i, ch in enumerate(text[start_idx:], start=start_idx):
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return safe_json_loads(text[start_idx : i + 1])

    return None


# ── Text helpers ──────────────────────────────────────────────────────────────

def truncate(text: str, max_len: int = 500) -> str:
    """Truncate text to max_len characters with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def clean_text(text: str) -> str:
    """Collapse whitespace and strip a string."""
    return re.sub(r"\s+", " ", text).strip()


def sanitize_filename(name: str) -> str:
    """Remove characters unsafe for filenames."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


# ── Validation helpers ────────────────────────────────────────────────────────

def is_valid_url(url: str) -> bool:
    """Basic URL validation."""
    pattern = re.compile(
        r"^https?://"
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
        r"localhost|"
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
        r"(?::\d+)?"
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )
    return bool(pattern.match(url))
