"""
backend/agents/memory_agent.py
================================
Memory Agent — stores and retrieves task context, search history,
collected jobs, and extracted data using ChromaDB vector store.
"""

from typing import Any, Callable, Dict, List, Optional

from backend.memory.chroma_store import ChromaStore
from backend.utils.helpers import hash_string, utc_now_iso
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryAgent:
    """
    Manages persistent agent memory via ChromaDB.

    Collections:
    - agent_memory: General task context and history
    - jobs: Collected job listings
    - searches: Previous search queries and results
    """

    COLLECTION_MEMORY  = "agent_memory"
    COLLECTION_JOBS    = "jobs"
    COLLECTION_SEARCH  = "searches"

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)
        self.store = ChromaStore.get_instance()

    # ── Task memory ───────────────────────────────────────────────────────────

    async def store_task_result(self, task_id: str, prompt: str, result: Any) -> None:
        """Persist task prompt and result to long-term memory."""
        try:
            doc_id = hash_string(f"task_{task_id}")
            self.store.upsert(
                collection_name=self.COLLECTION_MEMORY,
                doc_id=doc_id,
                text=f"Task: {prompt}\nResult summary: {str(result)[:500]}",
                metadata={
                    "type": "task_result",
                    "task_id": task_id,
                    "prompt": prompt[:200],
                    "timestamp": utc_now_iso(),
                },
            )
            self.log("info", "💾 Task result saved to memory")
        except Exception as exc:
            logger.error(f"Failed to store task result: {exc}")

    async def get_similar_tasks(self, prompt: str, n: int = 3) -> List[Dict[str, Any]]:
        """Find previous similar tasks (to avoid repeating work)."""
        try:
            return self.store.search(
                collection_name=self.COLLECTION_MEMORY,
                query=prompt,
                n_results=n,
                filter_metadata={"type": "task_result"},
            )
        except Exception as exc:
            logger.error(f"Memory search failed: {exc}")
            return []

    # ── Job memory ────────────────────────────────────────────────────────────

    async def store_jobs(self, jobs: List[Dict[str, Any]]) -> int:
        """
        Store a list of job listings in memory.
        Returns number of new jobs stored (skips duplicates).
        """
        stored = 0
        for job in jobs:
            try:
                # Deduplicate by company+role hash
                doc_id = hash_string(f"{job.get('company', '')}{job.get('role', '')}")
                text = f"{job.get('role', '')} at {job.get('company', '')} — {job.get('location', '')}. Skills: {', '.join(job.get('skills', []))}"
                self.store.upsert(
                    collection_name=self.COLLECTION_JOBS,
                    doc_id=doc_id,
                    text=text,
                    metadata={
                        "type": "job",
                        "company": job.get("company", ""),
                        "role": job.get("role", ""),
                        "location": job.get("location", ""),
                        "salary": job.get("salary", ""),
                        "apply_link": job.get("apply_link", ""),
                        "source_url": job.get("source_url", ""),
                        "timestamp": utc_now_iso(),
                    },
                )
                stored += 1
            except Exception as exc:
                logger.debug(f"Failed to store job: {exc}")
        return stored

    async def get_all_jobs(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Retrieve all stored job listings."""
        try:
            entries = self.store.get_all(
                collection_name=self.COLLECTION_JOBS,
                limit=limit,
            )
            # Reconstruct job dicts from metadata
            jobs = []
            for entry in entries:
                meta = entry.get("metadata", {})
                if meta.get("type") == "job":
                    jobs.append({
                        "company": meta.get("company", ""),
                        "role": meta.get("role", ""),
                        "location": meta.get("location", ""),
                        "salary": meta.get("salary", ""),
                        "apply_link": meta.get("apply_link", ""),
                        "source_url": meta.get("source_url", ""),
                        "timestamp": meta.get("timestamp", ""),
                    })
            return jobs
        except Exception as exc:
            logger.error(f"Failed to retrieve jobs: {exc}")
            return []

    async def search_jobs(self, query: str, n: int = 10) -> List[Dict[str, Any]]:
        """Semantic search over stored job listings."""
        try:
            return self.store.search(
                collection_name=self.COLLECTION_JOBS,
                query=query,
                n_results=n,
            )
        except Exception as exc:
            logger.error(f"Job search failed: {exc}")
            return []

    # ── Search history ────────────────────────────────────────────────────────

    async def store_search(self, query: str, results_summary: str, source: str = "") -> None:
        """Record a completed search query."""
        try:
            doc_id = hash_string(f"search_{query}_{source}")
            self.store.upsert(
                collection_name=self.COLLECTION_SEARCH,
                doc_id=doc_id,
                text=f"Search: {query}\nSource: {source}\nResults: {results_summary[:300]}",
                metadata={
                    "type": "search",
                    "query": query[:200],
                    "source": source,
                    "timestamp": utc_now_iso(),
                },
            )
        except Exception as exc:
            logger.debug(f"Failed to store search: {exc}")

    async def was_searched(self, query: str, source: str = "") -> bool:
        """Check if a query has been searched before (avoid duplication)."""
        try:
            results = self.store.search(
                collection_name=self.COLLECTION_SEARCH,
                query=f"{query} {source}",
                n_results=1,
            )
            return len(results) > 0
        except Exception:
            return False
