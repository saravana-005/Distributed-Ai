from __future__ import annotations

from pathlib import Path
from typing import Any

from localmind.admin.queue import create_job, get_job_progress


def create_demo_job(
    database_path: str | Path,
    *,
    name: str = "demo",
    task_count: int = 20,
    task_type: str = "noop",
    duration_seconds: float = 2.0,
) -> dict[str, Any]:
    tasks = []
    for _ in range(max(1, int(task_count))):
        tasks.append({
            "type": task_type,
            "payload": {"duration": float(duration_seconds)},
            "max_attempts": 3,
        })
    return create_job(database_path, name=name, tasks=tasks)


def get_job_status(database_path: str | Path, job_id: str) -> dict[str, Any]:
    return get_job_progress(database_path, job_id)
