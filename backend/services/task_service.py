"""
backend/services/task_service.py
==================================
Core task management service.

Responsibilities:
- Create tasks and assign unique IDs
- Track task state: PENDING → RUNNING → COMPLETED / FAILED / CANCELLED
- Persist logs in real-time for SSE streaming
- Execute tasks via the LangGraph orchestrator
- Enforce timeouts and cancellation
"""

import asyncio
from typing import Any, Dict, List, Optional

from backend.utils.helpers import generate_task_id, utc_now_iso
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class TaskStatus:
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class TaskService:
    """In-memory task registry with async execution support."""

    def __init__(self):
        # task_id → task record dict
        self._tasks: Dict[str, Dict[str, Any]] = {}
        # task_id → asyncio.Task (for cancellation)
        self._running: Dict[str, asyncio.Task] = {}

    # ── Task lifecycle ────────────────────────────────────────────────────────

    async def create_task(
        self,
        prompt: str,
        max_steps: int = 20,
        headless: bool = False,
    ) -> str:
        """Register a new task and return its ID."""
        task_id = generate_task_id()
        self._tasks[task_id] = {
            "task_id": task_id,
            "prompt": prompt,
            "max_steps": max_steps,
            "headless": headless,
            "status": TaskStatus.PENDING,
            "created_at": utc_now_iso(),
            "started_at": None,
            "completed_at": None,
            "logs": [],
            "result": None,
            "error": None,
            "steps_completed": 0,
        }
        return task_id

    async def run_task(self, task_id: str) -> None:
        """Execute the task via LangGraph orchestrator (runs in background)."""
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found for execution")
            return

        self._update_task(task_id, status=TaskStatus.RUNNING, started_at=utc_now_iso())
        self._log(task_id, "info", f"🚀 Task started: {task['prompt']}")

        try:
            # Import orchestrator here to avoid circular imports
            from backend.config.settings import get_settings
            from backend.agents.orchestrator import AgentOrchestrator

            settings = get_settings()
            orchestrator = AgentOrchestrator(
                task_id=task_id,
                log_callback=lambda level, msg: self._log(task_id, level, msg),
            )

            # Run with timeout
            result = await asyncio.wait_for(
                orchestrator.execute(
                    prompt=task["prompt"],
                    max_steps=task["max_steps"],
                    headless=task["headless"],
                ),
                timeout=settings.task_timeout,
            )

            self._update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                completed_at=utc_now_iso(),
                result=result,
                steps_completed=result.get("steps_completed", 0) if isinstance(result, dict) else 0,
            )
            self._log(task_id, "success", "✅ Task completed successfully")
            logger.info(f"Task {task_id} completed")

        except asyncio.TimeoutError:
            msg = f"Task timed out after {get_settings().task_timeout}s"
            self._update_task(task_id, status=TaskStatus.FAILED, completed_at=utc_now_iso(), error=msg)
            self._log(task_id, "error", f"⏰ {msg}")
            logger.error(f"Task {task_id} timed out")

        except asyncio.CancelledError:
            self._update_task(task_id, status=TaskStatus.CANCELLED, completed_at=utc_now_iso())
            self._log(task_id, "warn", "🛑 Task was cancelled")
            logger.info(f"Task {task_id} cancelled")

        except Exception as exc:
            error_msg = str(exc)
            self._update_task(
                task_id,
                status=TaskStatus.FAILED,
                completed_at=utc_now_iso(),
                error=error_msg,
            )
            self._log(task_id, "error", f"❌ Task failed: {error_msg}")
            logger.exception(f"Task {task_id} failed with exception")

        finally:
            self._running.pop(task_id, None)

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve task record by ID."""
        return self._tasks.get(task_id)

    async def list_tasks(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent tasks (newest first)."""
        all_tasks = list(self._tasks.values())
        all_tasks.sort(key=lambda t: t["created_at"], reverse=True)
        return all_tasks[:limit]

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        if task_id not in self._tasks:
            return False

        task = self._tasks[task_id]
        if task["status"] not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return False

        # Cancel the asyncio task if running
        running_task = self._running.get(task_id)
        if running_task and not running_task.done():
            running_task.cancel()

        self._update_task(task_id, status=TaskStatus.CANCELLED, completed_at=utc_now_iso())
        return True

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _update_task(self, task_id: str, **kwargs) -> None:
        """Merge keyword args into the task record."""
        if task_id in self._tasks:
            self._tasks[task_id].update(kwargs)

    def _log(self, task_id: str, level: str, message: str) -> None:
        """Append a structured log entry to the task's log list."""
        entry = {
            "timestamp": utc_now_iso(),
            "level": level,
            "message": message,
        }
        if task_id in self._tasks:
            self._tasks[task_id]["logs"].append(entry)
        logger.debug(f"[{task_id}] [{level.upper()}] {message}")
