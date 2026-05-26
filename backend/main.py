"""
backend/main.py
================
FastAPI application entry point.

- Configures CORS for frontend
- Registers all API routers
- Manages application lifespan (startup / shutdown)
- Serves frontend static files for convenience
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import sys, io
# Force UTF-8 output on Windows (needed for emoji in log messages)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from backend.config.logging_config import setup_logging
from backend.config.settings import get_settings
from backend.routes.task_routes import router as task_router
from backend.routes.upload_routes import router as upload_router
from backend.routes.history_routes import router as history_router
from backend.utils.logger import get_logger

# ── Initialise logging before anything else ──────────────────────────────────
setup_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    logger.info("🚀 Autonomous Browser Agent starting up…")

    # Ensure required directories exist
    for directory in [settings.upload_dir, settings.log_dir, settings.chroma_db_path]:
        Path(directory).mkdir(parents=True, exist_ok=True)
        logger.debug(f"Directory ensured: {directory}")

    # Import and initialise the ChromaDB memory store
    from backend.memory.chroma_store import ChromaStore
    ChromaStore.get_instance()
    logger.info("✅ ChromaDB memory store initialised")

    yield  # Application runs here

    logger.info("🛑 Autonomous Browser Agent shutting down…")


# ── Application factory ───────────────────────────────────────────────────────
app = FastAPI(
    title="Autonomous Browser Agent",
    description="AI-powered autonomous browser agent with LangGraph orchestration",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routers ───────────────────────────────────────────────────────────────
app.include_router(task_router,   prefix="/api", tags=["Tasks"])
app.include_router(upload_router, prefix="/api", tags=["Uploads"])
app.include_router(history_router, prefix="/api", tags=["History"])

# ── Serve frontend static files ───────────────────────────────────────────────
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        """Serve the frontend index.html."""
        return FileResponse(str(frontend_dir / "index.html"))


# ── Health check ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health_check():
    """Quick health probe for monitoring."""
    return {"status": "ok", "service": "autonomous-browser-agent"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
        log_level=settings.app_log_level.lower(),
    )
