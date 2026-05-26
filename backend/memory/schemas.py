"""
backend/memory/schemas.py
===========================
Pydantic schemas for memory records stored in ChromaDB.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from backend.utils.helpers import utc_now_iso


class MemoryRecord(BaseModel):
    """Base schema for any memory entry."""
    doc_id: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utc_now_iso)


class JobRecord(BaseModel):
    """Structured schema for a job listing memory entry."""
    company: str = ""
    role: str = ""
    location: str = ""
    salary: str = "Not specified"
    skills: List[str] = Field(default_factory=list)
    apply_link: str = ""
    source: str = ""
    source_url: str = ""
    job_type: str = "unknown"
    description: str = ""
    timestamp: str = Field(default_factory=utc_now_iso)

    def to_text(self) -> str:
        """Convert to searchable text for ChromaDB embedding."""
        return (
            f"{self.role} at {self.company} | {self.location} | "
            f"Skills: {', '.join(self.skills)} | {self.description}"
        )

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "type": "job",
            "company": self.company,
            "role": self.role,
            "location": self.location,
            "salary": self.salary,
            "apply_link": self.apply_link,
            "source": self.source,
            "source_url": self.source_url,
            "job_type": self.job_type,
            "timestamp": self.timestamp,
        }


class SearchRecord(BaseModel):
    """Schema for a recorded search query."""
    query: str
    source: str = ""
    results_count: int = 0
    timestamp: str = Field(default_factory=utc_now_iso)

    def to_text(self) -> str:
        return f"Search: {self.query} on {self.source}"

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "type": "search",
            "query": self.query,
            "source": self.source,
            "results_count": self.results_count,
            "timestamp": self.timestamp,
        }


class TaskRecord(BaseModel):
    """Schema for a completed task record."""
    task_id: str
    prompt: str
    status: str = "completed"
    result_summary: str = ""
    jobs_found: int = 0
    timestamp: str = Field(default_factory=utc_now_iso)

    def to_text(self) -> str:
        return f"Task: {self.prompt}\nResult: {self.result_summary}"

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "type": "task",
            "task_id": self.task_id,
            "prompt": self.prompt[:200],
            "status": self.status,
            "jobs_found": self.jobs_found,
            "timestamp": self.timestamp,
        }
