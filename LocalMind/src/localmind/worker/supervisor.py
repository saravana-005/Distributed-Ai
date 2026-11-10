from __future__ import annotations

import multiprocessing as mp
import time
from typing import Any


def _noop_executor(payload: dict[str, Any]) -> dict[str, Any]:
    duration = float(payload.get("duration", 0.0))
    if duration > 0:
        time.sleep(min(duration, 300.0))
    return {"status": "ok", "task": "noop", "duration": duration}


def _cpu_burn_executor(payload: dict[str, Any]) -> dict[str, Any]:
    duration = float(payload.get("duration", 0.0))
    limit = min(max(duration, 0.0), 600.0)
    start = time.perf_counter()
    total = 0
    while time.perf_counter() - start < limit:
        total += 1
        for _ in range(2000):
            total *= 1
    return {"status": "ok", "task": "cpu_burn", "duration": limit, "cycles": total}


def _run_task(task_type: str, payload: dict[str, Any], queue: mp.Queue) -> None:
    try:
        if task_type == "noop":
            result = _noop_executor(payload)
        elif task_type == "cpu_burn":
            result = _cpu_burn_executor(payload)
        else:
            raise ValueError(f"unsupported task type: {task_type}")
        queue.put({"ok": True, "result": result})
    except (TypeError, ValueError, RuntimeError, OSError, TimeoutError) as exc:  # pragma: no cover
        queue.put({"ok": False, "error": str(exc)})


def run_supervised_task(task_type: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue()
    process = ctx.Process(target=_run_task, args=(task_type, payload, queue), daemon=True)
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(1)
        raise TimeoutError(f"task {task_type} exceeded timeout {timeout}s")
    if queue.empty():
        raise RuntimeError(f"task {task_type} produced no result")
    result = queue.get()
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "task execution failed"))
    return result.get("result", {})


def validate_task_payload(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("task payload must be a JSON object")
    if task_type == "noop":
        duration = float(payload.get("duration", 0.0))
        if duration < 0 or duration > 600:
            raise ValueError("noop duration must be between 0 and 600 seconds")
        return {"duration": duration}
    if task_type == "cpu_burn":
        duration = float(payload.get("duration", 0.0))
        if duration < 0 or duration > 600:
            raise ValueError("cpu_burn duration must be between 0 and 600 seconds")
        return {"duration": duration}
    raise ValueError(f"unsupported task type: {task_type}")


__all__ = ["run_supervised_task", "validate_task_payload"]
