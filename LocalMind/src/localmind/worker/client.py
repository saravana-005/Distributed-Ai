from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from localmind.common.protocol import PROTOCOL_VERSION

SUPPORTED_TASK_TYPES = frozenset({"noop", "cpu_burn"})


class WorkerClient:
    def __init__(self, admin_url: str, worker_token: str, worker_id: str | None = None):
        self.admin_url = admin_url.rstrip("/")
        self.worker_token = worker_token
        self.worker_id = worker_id

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> tuple[int, dict[str, Any] | None, str | None]:
        headers = {"X-LocalMind-Protocol": str(PROTOCOL_VERSION), "Authorization": f"Bearer {self.worker_token}"}
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(urljoin(self.admin_url + "/", path), data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace") or "{}"
                try:
                    return response.status, json.loads(raw), None
                except json.JSONDecodeError:
                    return response.status, None, raw
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(raw), raw
            except json.JSONDecodeError:
                return exc.code, None, raw
        except (URLError, TimeoutError, OSError) as exc:
            return 0, None, str(exc)

    def heartbeat(self) -> bool:
        status, _, error = self.request("api/worker/heartbeat", method="POST", payload={"online": True}, timeout=10)
        if status in (401, 403):
            raise PermissionError("worker authentication failed")
        return status == 200 and error is None

    def claim_task(self) -> dict[str, Any] | None:
        status, data, _ = self.request("api/worker/claim", method="POST", payload={}, timeout=10)
        if status in (401, 403):
            raise PermissionError("worker authentication failed")
        if status != 200 or not isinstance(data, dict):
            return None
        task = data.get("task")
        if not task:
            return None
        return task

    def complete_task(self, task_id: str, result: dict[str, Any]) -> bool:
        status, _, _ = self.request(f"api/worker/tasks/{task_id}/complete", method="POST", payload={"result": result}, timeout=10)
        if status in (401, 403):
            raise PermissionError("worker authentication failed")
        return status == 200

    def fail_task(self, task_id: str, error: str) -> bool:
        status, _, _ = self.request(f"api/worker/tasks/{task_id}/fail", method="POST", payload={"error": error}, timeout=10)
        if status in (401, 403):
            raise PermissionError("worker authentication failed")
        return status == 200

    def extend_task(self, task_id: str, lease_seconds: int = 60) -> bool:
        status, _, _ = self.request(f"api/worker/tasks/{task_id}/extend", method="POST", payload={"lease_seconds": lease_seconds}, timeout=10)
        if status in (401, 403):
            raise PermissionError("worker authentication failed")
        return status == 200
