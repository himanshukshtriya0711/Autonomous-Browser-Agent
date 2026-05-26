"""
setup.py (helper script — not for packaging)
=============================================
Run this once after cloning to install all deps + Playwright browsers.

Usage:
    python setup.py
"""

import subprocess
import sys
import os
from pathlib import Path


def run(cmd: str, check: bool = True):
    print(f"\n▶  {cmd}")
    result = subprocess.run(cmd, shell=True, check=check)
    return result.returncode == 0


def main():
    print("=" * 60)
    print("  Autonomous Browser Agent — Setup")
    print("=" * 60)

    # 1. Install Python packages
    print("\n[1/3] Installing Python packages…")
    run(f"{sys.executable} -m pip install --upgrade pip")
    run(f"{sys.executable} -m pip install -r requirements.txt")

    # 2. Install Playwright browsers
    print("\n[2/3] Installing Playwright Chromium browser…")
    run("playwright install chromium")

    # 3. Check .env
    print("\n[3/3] Checking .env configuration…")
    env_path = Path(".env")
    if not env_path.exists():
        print("  ⚠️  .env not found. Creating from template…")
        template = Path(".env")
        if template.exists():
            import shutil
            shutil.copy(str(template), ".env")
        print("  ✏️  Edit .env and set your GROQ_API_KEY")
    else:
        content = env_path.read_text()
        if "your_groq_api_key_here" in content:
            print("  ⚠️  GROQ_API_KEY is still the placeholder!")
            print("  ✏️  Edit .env and set your real key from https://console.groq.com")
        else:
            print("  ✅ .env configured")

    print("\n" + "=" * 60)
    print("  ✅ Setup complete!")
    print()
    print("  Start the server:")
    print("    python -m uvicorn backend.main:app --reload --port 8000")
    print()
    print("  Or on Windows:")
    print("    start.bat")
    print()
    print("  Then open: http://localhost:8000")
    print("=" * 60)


if __name__ == "__main__":
    main()
