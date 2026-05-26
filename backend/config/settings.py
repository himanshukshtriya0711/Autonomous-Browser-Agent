"""
backend/config/settings.py
==========================
Central configuration management using Pydantic Settings.
All values are loaded from environment variables / .env file.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Groq LLM ─────────────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model_primary: str = "llama-3.3-70b-versatile"
    groq_model_reasoning: str = "deepseek-r1-distill-llama-70b"

    # ── Application ──────────────────────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True
    app_log_level: str = "INFO"

    # ── Storage paths ────────────────────────────────────────────────────────
    chroma_db_path: str = "./chroma_db"
    upload_dir: str = "./uploads"
    log_dir: str = "./logs"

    # ── Browser ──────────────────────────────────────────────────────────────
    browser_headless: bool = False
    browser_timeout: int = 30000       # milliseconds
    browser_slow_mo: int = 100          # milliseconds between actions

    # ── Agent behaviour ──────────────────────────────────────────────────────
    max_retries: int = 3
    task_timeout: int = 300             # seconds


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton settings instance."""
    return Settings()
