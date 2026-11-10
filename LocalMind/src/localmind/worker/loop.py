from __future__ import annotations

import random
import time
from typing import Any

from localmind.worker.client import SUPPORTED_TASK_TYPES, WorkerClient
from localmind.worker.config import load_worker_config
from localmind.worker.supervisor import run_supervised_task, validate_task_payload


class WorkerLoop:
    def __init__(self, admin_url: str, worker_token: str, worker_id: str | None = None):
        self.client = WorkerClient(admin_url, worker_token, worker_id)
        self.admin_url = self.client.admin_url
        self.worker_token = self.client.worker_token
        self.worker_id = self.client.worker_id

    def _request(self, path: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout: int = 10):
        return self.client.request(path, method=method, payload=payload, timeout=timeout)

    def heartbeat(self) -> bool:
        return self.client.heartbeat()

    def claim_task(self) -> dict[str, Any] | None:
        return self.client.claim_task()

    def complete_task(self, task_id: str, result: dict[str, Any]) -> bool:
        return self.client.complete_task(task_id, result)

    def fail_task(self, task_id: str, error: str) -> bool:
        return self.client.fail_task(task_id, error)

    def extend_task(self, task_id: str, lease_seconds: int = 60) -> bool:
        return self.client.extend_task(task_id, lease_seconds)

    def run_once(self) -> bool:
        task = self.claim_task()
        if not task:
            return False
        task_id = task.get("id")
        task_type = task.get("type")
        if task_type not in SUPPORTED_TASK_TYPES:
            if task_id is not None:
                self.fail_task(task_id, f"unsupported task type: {task_type}")
            return False
        try:
            payload = validate_task_payload(task_type, task.get("payload", {}))
        except (TypeError, ValueError) as exc:
            if task_id is not None:
                self.fail_task(task_id, str(exc))
            return False
        try:
            timeout_seconds = min(float(task.get("lease_seconds", 60)) + 5, 300.0)
            result = run_supervised_task(task_type, payload, timeout=timeout_seconds)
            if task_id is None:
                return False
            return self.complete_task(task_id, {"status": "ok", "result": result})
        except (RuntimeError, TimeoutError, ValueError, OSError) as exc:
            if task_id is not None:
                self.fail_task(task_id, str(exc))
            return False

    def run_forever(
        self,
        *,
        poll_interval: float = 1.0,
        heartbeat_interval: float = 30.0,
        max_backoff: float = 30.0,
        stop_event: Any | None = None,
    ) -> int:
        next_heartbeat = time.monotonic()
        backoff = 0.5
        while stop_event is None or not stop_event.is_set():
            try:
                now = time.monotonic()
                if now >= next_heartbeat:
                    self.heartbeat()
                    next_heartbeat = now + heartbeat_interval

                if self.run_once():
                    backoff = 0.5
                    time.sleep(poll_interval)
                    continue

                time.sleep(max(poll_interval, backoff))
                backoff = min(max_backoff, backoff * 2 + random.uniform(0.0, 0.5))
            except PermissionError:
                print("Worker authentication failed; stopping runtime.")
                return 1
            except (TimeoutError, OSError, ConnectionError):
                time.sleep(min(max_backoff, backoff))
                backoff = min(max_backoff, backoff * 2 + random.uniform(0.0, 0.5))
            except KeyboardInterrupt:
                print("Worker shutdown requested.")
                return 0
        return 0


def load_loop_from_config() -> WorkerLoop | None:
    config = load_worker_config()
    if config is None:
        return None
    return WorkerLoop(config["admin_url"], config["worker_token"], config.get("worker_id"))


__all__ = ["SUPPORTED_TASK_TYPES", "WorkerLoop", "load_loop_from_config"]
