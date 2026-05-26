"""
backend/routes/upload_routes.py
================================
Resume / document upload endpoints.

POST /api/upload-resume  — Upload PDF resume, extract profile data
GET  /api/resume         — Get currently loaded resume profile
"""

import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.config.settings import get_settings
from backend.tools.pdf_tool import PDFTool
from backend.utils.helpers import sanitize_filename, utc_now_iso
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()
settings = get_settings()

# In-memory cache of the latest parsed resume (per session)
_current_resume: dict = {}


@router.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    """
    Upload a PDF resume.
    Extracts text, parses skills/experience/education, returns structured profile.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    upload_path = Path(settings.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(file.filename)
    dest_path = upload_path / safe_name

    # Save uploaded file
    try:
        with dest_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        logger.error(f"Failed to save uploaded file: {exc}")
        raise HTTPException(status_code=500, detail="Failed to save file")

    logger.info(f"Resume uploaded: {safe_name}")

    # Parse resume using PDFTool
    try:
        pdf_tool = PDFTool()
        profile = await pdf_tool.parse_resume(str(dest_path))
    except Exception as exc:
        logger.error(f"Failed to parse resume: {exc}")
        raise HTTPException(status_code=500, detail=f"Resume parsing failed: {str(exc)}")

    global _current_resume
    _current_resume = {
        "filename": safe_name,
        "path": str(dest_path),
        "uploaded_at": utc_now_iso(),
        "profile": profile,
    }

    return {
        "success": True,
        "filename": safe_name,
        "profile": profile,
        "message": "Resume uploaded and parsed successfully",
    }


@router.get("/resume")
async def get_resume():
    """Return the currently loaded resume profile."""
    if not _current_resume:
        raise HTTPException(status_code=404, detail="No resume uploaded yet")
    return _current_resume
