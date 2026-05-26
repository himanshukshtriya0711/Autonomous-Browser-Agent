"""
test_imports.py
================
Quick validation script — run this after pip install to confirm
all backend modules import cleanly before starting the server.

Usage:
    venv\\Scripts\\python test_imports.py
"""

import sys

errors = []

def check(label: str, fn):
    try:
        fn()
        print(f"  ✅  {label}")
    except Exception as e:
        print(f"  ❌  {label}  →  {e}")
        errors.append(label)


print("\n════════════════════════════════════════════")
print("  Autonomous Browser Agent — Import Check")
print("════════════════════════════════════════════\n")

# Core framework
check("fastapi",             lambda: __import__("fastapi"))
check("uvicorn",             lambda: __import__("uvicorn"))
check("pydantic",            lambda: __import__("pydantic"))
check("pydantic_settings",   lambda: __import__("pydantic_settings"))
check("python-dotenv",       lambda: __import__("dotenv"))
check("python-multipart",    lambda: __import__("multipart"))

# LLM / AI
check("langchain",           lambda: __import__("langchain"))
check("langchain_groq",      lambda: __import__("langchain_groq"))
check("langchain_core",      lambda: __import__("langchain_core"))
check("langgraph",           lambda: __import__("langgraph"))
check("groq",                lambda: __import__("groq"))

# Browser
check("playwright",          lambda: __import__("playwright"))

# Memory
check("chromadb",            lambda: __import__("chromadb"))

# PDF
check("pymupdf (fitz)",      lambda: __import__("fitz"))

# HTTP / parsing
check("httpx",               lambda: __import__("httpx"))
check("aiohttp",             lambda: __import__("aiohttp"))
check("beautifulsoup4",      lambda: __import__("bs4"))
check("lxml",                lambda: __import__("lxml"))
check("tenacity",            lambda: __import__("tenacity"))

# Optional
print()
try:
    import browser_use  # noqa
    print("  ✅  browser-use (optional)")
except ImportError:
    print("  ⚠️   browser-use NOT installed (optional — agent will use direct Playwright fallback)")

# Backend modules
print("\n── Backend Modules ──────────────────────────")
sys.path.insert(0, ".")
check("backend.config.settings",        lambda: __import__("backend.config.settings", fromlist=[""]))
check("backend.utils.helpers",          lambda: __import__("backend.utils.helpers", fromlist=[""]))
check("backend.utils.logger",           lambda: __import__("backend.utils.logger", fromlist=[""]))
check("backend.memory.chroma_store",    lambda: __import__("backend.memory.chroma_store", fromlist=[""]))
check("backend.memory.schemas",         lambda: __import__("backend.memory.schemas", fromlist=[""]))
check("backend.agents.planner_agent",   lambda: __import__("backend.agents.planner_agent", fromlist=[""]))
check("backend.agents.extraction_agent",lambda: __import__("backend.agents.extraction_agent", fromlist=[""]))
check("backend.agents.recovery_agent",  lambda: __import__("backend.agents.recovery_agent", fromlist=[""]))
check("backend.tools.job_search_tool",  lambda: __import__("backend.tools.job_search_tool", fromlist=[""]))
check("backend.tools.pdf_tool",         lambda: __import__("backend.tools.pdf_tool", fromlist=[""]))
check("backend.tools.extraction_tool",  lambda: __import__("backend.tools.extraction_tool", fromlist=[""]))
check("backend.services.browser_service", lambda: __import__("backend.services.browser_service", fromlist=[""]))
check("backend.services.task_service",  lambda: __import__("backend.services.task_service", fromlist=[""]))

print("\n════════════════════════════════════════════")
if errors:
    print(f"  ⚠️   {len(errors)} issue(s) found: {', '.join(errors)}")
    print("  Fix the above before starting the server.")
else:
    print("  ✅  All checks passed! Start with:")
    print()
    print("      python -m uvicorn backend.main:app --reload --port 8000")
print("════════════════════════════════════════════\n")
