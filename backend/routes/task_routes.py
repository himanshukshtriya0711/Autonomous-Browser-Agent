"""
backend/routes/task_routes.py
==============================
Task API routes.

POST /api/task         — Submit a new agent task
GET  /api/task/{id}    — Poll task status + results
GET  /api/task/{id}/logs — Stream logs via Server-Sent Events
DELETE /api/task/{id}  — Cancel a running task
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.services.task_service import TaskService, TaskStatus
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()
task_service = TaskService()


# ── Request / Response schemas ────────────────────────────────────────────────

class TaskRequest(BaseModel):
    prompt: str = Field(..., min_length=3, description="Natural language instruction for the agent")
    max_steps: Optional[int] = Field(default=20, ge=1, le=50)
    headless: Optional[bool] = Field(default=False, description="Run browser headlessly")


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/task", response_model=TaskResponse, status_code=202)
async def submit_task(request: TaskRequest, background_tasks: BackgroundTasks):
    """
    Submit a natural-language task to the autonomous browser agent.
    Returns a task_id to poll for results.
    """
    task_id = await task_service.create_task(
        prompt=request.prompt,
        max_steps=request.max_steps,
        headless=request.headless,
    )

    # Run in background so API responds immediately
    background_tasks.add_task(task_service.run_task, task_id)

    logger.info(f"Task submitted: {task_id} | Prompt: {request.prompt[:80]}")
    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Task queued successfully. Poll /api/task/{task_id} for status.",
    )


@router.get("/task/{task_id}")
async def get_task(task_id: str):
    """Retrieve current status, logs, and results of a task."""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.get("/task/{task_id}/logs")
async def stream_task_logs(task_id: str):
    """
    Server-Sent Events stream of real-time agent logs for a task.
    Connect from frontend via EventSource('/api/task/{id}/logs').
    """
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    async def event_generator():
        last_index = 0
        while True:
            current_task = await task_service.get_task(task_id)
            if not current_task:
                break

            logs = current_task.get("logs", [])
            # Send any new log lines since last check
            for log_entry in logs[last_index:]:
                data = json.dumps(log_entry)
                yield f"data: {data}\n\n"
                last_index += 1

            # Stop streaming when task is terminal
            if current_task["status"] in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                yield f"data: {json.dumps({'type': 'done', 'status': current_task['status']})}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/task/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a running task."""
    cancelled = await task_service.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found or already finished")
    return {"task_id": task_id, "status": TaskStatus.CANCELLED, "message": "Task cancelled"}


@router.get("/tasks")
async def list_tasks(limit: int = 20):
    """List recent tasks with their statuses."""
    return await task_service.list_tasks(limit=limit)
