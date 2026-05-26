"""
backend/utils/compat.py
========================
Compatibility shims — gracefully handle optional dependencies
(browser-use, etc.) so the system works even if they are not installed.
"""

import importlib
from typing import Any, Optional


def try_import(module_name: str, package_name: Optional[str] = None) -> Optional[Any]:
    """
    Attempt to import a module.
    Returns the module on success, or None with a warning on failure.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError:
        pkg = package_name or module_name
        import logging
        logging.getLogger(__name__).warning(
            f"Optional dependency '{pkg}' not installed. "
            f"Install with: pip install {pkg}"
        )
        return None


# Feature flags — checked once at startup
HAS_BROWSER_USE = try_import("browser_use") is not None
HAS_PYMUPDF     = try_import("fitz", "pymupdf") is not None
HAS_CHROMADB    = try_import("chromadb") is not None
