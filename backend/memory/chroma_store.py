"""
backend/memory/chroma_store.py
================================
ChromaDB persistent vector store manager.

Provides a singleton ChromaStore with:
- Collection auto-creation
- Upsert (insert or update)
- Semantic search via embeddings
- Get all / delete / clear operations

Uses ChromaDB's default embedding function (sentence-transformers).
"""

import threading
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from backend.config.settings import get_settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)
app_settings = get_settings()


class ChromaStore:
    """
    Singleton wrapper around ChromaDB persistent client.
    Thread-safe via a class-level lock.
    """

    _instance: Optional["ChromaStore"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        self._client = chromadb.PersistentClient(
            path=app_settings.chroma_db_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        # Cache of collection handles
        self._collections: Dict[str, Any] = {}
        logger.info(f"ChromaDB initialised at: {app_settings.chroma_db_path}")

    @classmethod
    def get_instance(cls) -> "ChromaStore":
        """Return (or create) the singleton ChromaStore."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Collection management ─────────────────────────────────────────────────

    def _get_or_create_collection(self, collection_name: str) -> Any:
        """Return a ChromaDB collection, creating it if it doesn't exist."""
        if collection_name not in self._collections:
            self._collections[collection_name] = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[collection_name]

    # ── CRUD operations ───────────────────────────────────────────────────────

    def upsert(
        self,
        collection_name: str,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert or update a document in a collection."""
        try:
            col = self._get_or_create_collection(collection_name)
            # ChromaDB metadata values must be str, int, float, or bool
            safe_meta = self._sanitize_metadata(metadata or {})
            col.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[safe_meta],
            )
        except Exception as exc:
            logger.error(f"ChromaDB upsert failed [{collection_name}]: {exc}")
            raise

    def search(
        self,
        collection_name: str,
        query: str,
        n_results: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search in a collection.
        Returns list of {id, text, metadata, distance} dicts.
        """
        try:
            col = self._get_or_create_collection(collection_name)
            count = col.count()
            if count == 0:
                return []

            kwargs: Dict[str, Any] = {
                "query_texts": [query],
                "n_results": min(n_results, count),
                "include": ["documents", "metadatas", "distances"],
            }
            if filter_metadata:
                kwargs["where"] = filter_metadata

            results = col.query(**kwargs)

            formatted = []
            ids       = results.get("ids", [[]])[0]
            docs      = results.get("documents", [[]])[0]
            metas     = results.get("metadatas", [[]])[0]
            dists     = results.get("distances", [[]])[0]

            for i, doc_id in enumerate(ids):
                formatted.append({
                    "id":       doc_id,
                    "text":     docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {},
                    "distance": dists[i] if i < len(dists) else 1.0,
                })

            return formatted

        except Exception as exc:
            logger.error(f"ChromaDB search failed [{collection_name}]: {exc}")
            return []

    def get_all(
        self,
        collection_name: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Retrieve all documents from a collection (up to limit)."""
        try:
            col = self._get_or_create_collection(collection_name)
            count = col.count()
            if count == 0:
                return []

            results = col.get(
                limit=min(limit, count),
                include=["documents", "metadatas"],
            )

            formatted = []
            ids   = results.get("ids", [])
            docs  = results.get("documents", [])
            metas = results.get("metadatas", [])

            for i, doc_id in enumerate(ids):
                formatted.append({
                    "id":       doc_id,
                    "text":     docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {},
                })

            return formatted

        except Exception as exc:
            logger.error(f"ChromaDB get_all failed [{collection_name}]: {exc}")
            return []

    def delete(self, collection_name: str, doc_id: str) -> bool:
        """Delete a single document by ID."""
        try:
            col = self._get_or_create_collection(collection_name)
            col.delete(ids=[doc_id])
            return True
        except Exception as exc:
            logger.error(f"ChromaDB delete failed [{collection_name}]: {exc}")
            return False

    def clear_collection(self, collection_name: str) -> None:
        """Delete and recreate a collection (full wipe)."""
        try:
            self._client.delete_collection(collection_name)
            # Remove from cache so it gets recreated on next access
            self._collections.pop(collection_name, None)
            logger.info(f"Collection cleared: {collection_name}")
        except Exception as exc:
            logger.error(f"Failed to clear collection [{collection_name}]: {exc}")

    def list_collections(self) -> List[str]:
        """Return names of all existing collections."""
        try:
            return [col.name for col in self._client.list_collections()]
        except Exception as exc:
            logger.error(f"Failed to list collections: {exc}")
            return []

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        ChromaDB only accepts str/int/float/bool metadata values.
        Convert everything else to string.
        """
        clean: Dict[str, Any] = {}
        for k, v in meta.items():
            if isinstance(v, (str, int, float, bool)):
                clean[k] = v
            elif isinstance(v, list):
                clean[k] = ", ".join(str(i) for i in v)
            elif v is None:
                clean[k] = ""
            else:
                clean[k] = str(v)
        return clean
