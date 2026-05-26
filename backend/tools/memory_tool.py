"""
backend/tools/memory_tool.py
==============================
Memory Tool — thin convenience wrapper around ChromaStore and MemoryAgent
for direct use inside tool chains without needing the full agent.
"""

from typing import Any, Callable, Dict, List, Optional

from backend.memory.chroma_store import ChromaStore
from backend.utils.helpers import hash_string, utc_now_iso
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryTool:
    """
    Provides simple save / search / retrieve operations on ChromaDB
    for direct use from tools and services.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: None)
        self.store = ChromaStore.get_instance()

    def save(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        collection: str = "agent_memory",
    ) -> str:
        """
        Save a text document to memory.
        Returns the document ID.
        """
        doc_id = hash_string(f"{text[:100]}_{utc_now_iso()}")
        self.store.upsert(
            collection_name=collection,
            doc_id=doc_id,
            text=text,
            metadata=metadata or {"timestamp": utc_now_iso()},
        )
        self.log("info", f"💾 Saved to memory [{collection}]: {text[:50]}…")
        return doc_id

    def search(
        self,
        query: str,
        collection: str = "agent_memory",
        n_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Semantic search in a memory collection."""
        return self.store.search(
            collection_name=collection,
            query=query,
            n_results=n_results,
        )

    def get_all(
        self,
        collection: str = "agent_memory",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve all entries from a collection."""
        return self.store.get_all(collection_name=collection, limit=limit)

    def delete(self, doc_id: str, collection: str = "agent_memory") -> bool:
        """Delete a specific document by ID."""
        return self.store.delete(collection_name=collection, doc_id=doc_id)

    def clear(self, collection: str = "agent_memory") -> None:
        """Clear all entries in a collection."""
        self.store.clear_collection(collection_name=collection)
        self.log("warn", f"🗑️ Cleared collection: {collection}")

    def collection_info(self, collection: str = "agent_memory") -> Dict[str, Any]:
        """Return metadata about a collection."""
        try:
            col = self.store._get_or_create_collection(collection)
            return {"name": collection, "count": col.count()}
        except Exception as exc:
            return {"name": collection, "error": str(exc)}
