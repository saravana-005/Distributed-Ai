from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from localmind.admin.db import database_connection

TASK_PENDING = "PENDING"
TASK_LEASED = "LEASED"
TASK_COMPLETED = "COMPLETED"
TASK_FAILED = "FAILED"

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_loads(value: Any) -> Any:
    if value in (None, ""):
        return {}
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return {}


def _json_dumps(value: Any) -> str:
    if value is None:
        return "{}"
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _task_state_summary(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return JOB_QUEUED
    states = {task.get("state") for task in tasks}
    if any(task.get("state") == TASK_FAILED for task in tasks):
        return JOB_FAILED
    if any(task.get("state") == TASK_LEASED for task in tasks):
        return JOB_RUNNING
    if states == {TASK_COMPLETED}:
        return JOB_COMPLETED
    if {TASK_COMPLETED, TASK_PENDING}.issubset(states):
        return JOB_RUNNING
    return JOB_QUEUED


def _refresh_job_state(connection: Any, job_id: str) -> str:
    rows = connection.execute(
        "SELECT state FROM tasks WHERE job_id = ?",
        (job_id,),
    ).fetchall()
    if not rows:
        connection.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (
                JOB_QUEUED,
                utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                job_id,
            ),
        )
        return JOB_QUEUED

    states = [dict(row).get("state") for row in rows]
    status = _task_state_summary([{"state": state} for state in states])
    completed = sum(1 for state in states if state == TASK_COMPLETED)
    failed = sum(1 for state in states if state == TASK_FAILED)
    connection.execute(
        "UPDATE jobs SET status = ?, updated_at = ?, total_tasks = ?, completed_tasks = ?, failed_tasks = ? WHERE id = ?",
        (
            status,
            utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            len(states),
            completed,
            failed,
            job_id,
        ),
    )
    return status


def create_job(
    database_path: str | Path,
    *,
    name: str,
    tasks: list[dict[str, Any]] | None = None,
    status: str = JOB_QUEUED,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    job_id = secrets.token_hex(12)
    now = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    with database_connection(database_path) as conn:
        conn.execute(
            "INSERT INTO jobs (id, name, status, dataset_id, created_at, updated_at, cancelled, total_tasks, completed_tasks, failed_tasks) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0)",
            (job_id, name, status, dataset_id, now, now),
        )
        rows = tasks or []
        for index, task in enumerate(rows):
            task_type = str(task.get("type") or "noop")
            payload = _json_dumps(task.get("payload") or {})
            max_attempts = int(task.get("max_attempts") or 3)
            conn.execute(
                "INSERT INTO tasks (id, job_id, type, payload, status, state, attempts, max_attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (
                    f"{job_id}-{index:04d}",
                    job_id,
                    task_type,
                    payload,
                    TASK_PENDING,
                    TASK_PENDING,
                    max_attempts,
                    now,
                    now,
                ),
            )
        conn.execute(
            "UPDATE jobs SET total_tasks = (SELECT COUNT(*) FROM tasks WHERE job_id = ?), updated_at = ? WHERE id = ?",
            (job_id, now, job_id),
        )
        conn.commit()
        return {
            "id": job_id,
            "name": name,
            "status": JOB_QUEUED,
            "dataset_id": dataset_id,
            "total_tasks": len(rows),
        }


def claim_task(
    database_path: str | Path,
    *,
    worker_id: str,
    lease_seconds: int = 60,
) -> dict[str, Any] | None:
    with database_connection(database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                """
                SELECT t.id, t.job_id, t.type, t.payload, t.attempts, t.max_attempts
                FROM tasks t
                JOIN jobs j ON j.id = t.job_id
                WHERE t.state = ? AND j.cancelled = 0 AND t.attempts < t.max_attempts
                ORDER BY t.created_at ASC
                LIMIT 1
                """,
                (TASK_PENDING,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            lease_expires = (utc_now() + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
            next_attempt = int(row["attempts"]) + 1
            now = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
            cur = conn.execute(
                """
                UPDATE tasks
                SET state = ?, status = ?, assigned_worker_id = ?, attempts = ?, lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND state = ?
                """,
                (
                    TASK_LEASED,
                    TASK_LEASED,
                    worker_id,
                    next_attempt,
                    lease_expires,
                    now,
                    row["id"],
                    TASK_PENDING,
                ),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return None
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (JOB_RUNNING, now, row["job_id"]),
            )
            conn.commit()
            return {
                "id": row["id"],
                "job_id": row["job_id"],
                "type": row["type"],
                "payload": _json_loads(row["payload"]),
                "attempts": next_attempt,
                "lease_expires_at": lease_expires,
                "lease_seconds": lease_seconds,
                "worker_id": worker_id,
            }
        except Exception:
            conn.rollback()
            raise


def extend_task_lease(
    database_path: str | Path,
    *,
    task_id: str,
    worker_id: str,
    lease_seconds: int = 60,
) -> dict[str, Any]:
    now = utc_now()
    with database_connection(database_path) as conn:
        row = conn.execute(
            "SELECT id, state, assigned_worker_id FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("task_not_found")
        if row["state"] != TASK_LEASED:
            raise ValueError("task_not_leased")
        if row["assigned_worker_id"] != worker_id:
            raise ValueError("wrong_worker")
        new_expiry = (now + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE tasks SET lease_expires_at = ?, updated_at = ? WHERE id = ?",
            (new_expiry, now.strftime("%Y-%m-%dT%H:%M:%SZ"), task_id),
        )
        conn.commit()
        return {"task_id": task_id, "lease_expires_at": new_expiry}


def complete_task(
    database_path: str | Path,
    *,
    task_id: str,
    worker_id: str,
    result: Any,
) -> dict[str, Any]:
    now = utc_now()
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    with database_connection(database_path) as conn:
        row = conn.execute(
            "SELECT id, job_id, state, assigned_worker_id, lease_expires_at FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("task_not_found")
        if row["state"] != TASK_LEASED:
            raise ValueError("task_not_leased")
        if row["assigned_worker_id"] != worker_id:
            raise ValueError("wrong_worker")
        if row["lease_expires_at"] and row["lease_expires_at"] < now_str:
            raise ValueError("lease_expired")
        conn.execute(
            "UPDATE tasks SET state = ?, status = ?, result = ?, completed_at = ?, lease_expires_at = NULL, assigned_worker_id = NULL, updated_at = ? WHERE id = ?",
            (TASK_COMPLETED, TASK_COMPLETED, _json_dumps(result), now_str, now_str, task_id),
        )
        _refresh_job_state(conn, row["job_id"])
        conn.commit()
        return {"task_id": task_id, "status": TASK_COMPLETED}


def fail_task(
    database_path: str | Path,
    *,
    task_id: str,
    worker_id: str,
    error: str,
) -> dict[str, Any]:
    now = utc_now()
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    with database_connection(database_path) as conn:
        row = conn.execute(
            "SELECT id, job_id, state, assigned_worker_id FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("task_not_found")
        if row["state"] != TASK_LEASED:
            raise ValueError("task_not_leased")
        if row["assigned_worker_id"] != worker_id:
            raise ValueError("wrong_worker")
        conn.execute(
            "UPDATE tasks SET state = ?, status = ?, error = ?, completed_at = ?, lease_expires_at = NULL, assigned_worker_id = NULL, updated_at = ? WHERE id = ?",
            (TASK_FAILED, TASK_FAILED, str(error)[:2048], now_str, now_str, task_id),
        )
        _refresh_job_state(conn, row["job_id"])
        conn.commit()
        return {"task_id": task_id, "status": TASK_FAILED}


def recover_expired_leases(database_path: str | Path) -> list[str]:
    now = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    with database_connection(database_path) as conn:
        rows = conn.execute(
            "SELECT id, job_id, attempts, max_attempts FROM tasks WHERE state = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
            (TASK_LEASED, now),
        ).fetchall()
        recovered: list[str] = []
        for row in rows:
            if int(row["attempts"]) >= int(row["max_attempts"]):
                conn.execute(
                    "UPDATE tasks SET state = ?, status = ?, error = ?, completed_at = ?, lease_expires_at = NULL, assigned_worker_id = NULL, updated_at = ? WHERE id = ?",
                    (TASK_FAILED, TASK_FAILED, "lease_expired", now, now, row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE tasks SET state = ?, status = ?, assigned_worker_id = NULL, lease_expires_at = NULL, updated_at = ? WHERE id = ?",
                    (TASK_PENDING, TASK_PENDING, now, row["id"]),
                )
                recovered.append(row["id"])
            _refresh_job_state(conn, row["job_id"])
        conn.commit()
        return recovered


def get_job_progress(database_path: str | Path, job_id: str) -> dict[str, Any]:
    with database_connection(database_path) as conn:
        job = conn.execute(
            "SELECT id, name, status, cancelled, total_tasks, completed_tasks, failed_tasks FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if job is None:
            raise ValueError("job_not_found")
        tasks = conn.execute(
            "SELECT state FROM tasks WHERE job_id = ? ORDER BY created_at ASC",
            (job_id,),
        ).fetchall()
        total = len(tasks)
        completed = sum(1 for row in tasks if row["state"] == TASK_COMPLETED)
        failed = sum(1 for row in tasks if row["state"] == TASK_FAILED)
        pending = sum(1 for row in tasks if row["state"] == TASK_PENDING)
        leased = sum(1 for row in tasks if row["state"] == TASK_LEASED)
        progress = 0 if total == 0 else round((completed / total) * 100, 2)
        return {
            "job_id": job["id"],
            "name": job["name"],
            "status": job["status"],
            "cancelled": bool(job["cancelled"]),
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "leased": leased,
            "progress": progress,
        }


def cancel_job(database_path: str | Path, job_id: str) -> dict[str, Any]:
    with database_connection(database_path) as conn:
        row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("job_not_found")
        conn.execute(
            "UPDATE jobs SET cancelled = 1, status = ?, updated_at = ? WHERE id = ?",
            (JOB_CANCELLED, utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"), job_id),
        )
        conn.execute(
            "UPDATE tasks SET state = ?, status = ?, assigned_worker_id = NULL, lease_expires_at = NULL WHERE job_id = ? AND state = ?",
            (TASK_PENDING, TASK_PENDING, job_id, TASK_PENDING),
        )
        conn.commit()
        return {"job_id": job_id, "status": JOB_CANCELLED}
