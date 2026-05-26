"""
backend/routes/history_routes.py
==================================
Agent history and memory retrieval endpoints.

GET /api/history           — List all stored memory entries
GET /api/history/jobs      — List collected jobs from memory
GET /api/history/search    — Search memory by query
DELETE /api/history        — Clear all memory
"""

from fastapi import APIRouter, HTTPException, Query

from backend.memory.chroma_store import ChromaStore
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/history")
async def get_history(limit: int = Query(default=50, ge=1, le=200)):
    """Return all stored agent memory entries."""
    try:
        store = ChromaStore.get_instance()
        entries = store.get_all(collection_name="agent_memory", limit=limit)
        return {"count": len(entries), "entries": entries}
    except Exception as exc:
        logger.error(f"History retrieval failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history/jobs")
async def get_job_history(limit: int = Query(default=100, ge=1, le=500)):
    """Return all collected job listings from memory."""
    try:
        store = ChromaStore.get_instance()
        entries = store.get_all(collection_name="jobs", limit=limit)
        return {"count": len(entries), "jobs": entries}
    except Exception as exc:
        logger.error(f"Job history retrieval failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history/search")
async def search_history(
    q: str = Query(..., description="Search query"),
    collection: str = Query(default="agent_memory"),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Semantic search across agent memory."""
    try:
        store = ChromaStore.get_instance()
        results = store.search(collection_name=collection, query=q, n_results=limit)
        return {"query": q, "count": len(results), "results": results}
    except Exception as exc:
        logger.error(f"Memory search failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/history")
async def clear_history(collection: str = Query(default="agent_memory")):
    """Clear a specific memory collection."""
    try:
        store = ChromaStore.get_instance()
        store.clear_collection(collection_name=collection)
        return {"success": True, "message": f"Collection '{collection}' cleared"}
    except Exception as exc:
        logger.error(f"Failed to clear history: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
