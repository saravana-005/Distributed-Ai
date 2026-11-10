from __future__ import annotations

import argparse

from localmind.worker import main as worker_main
from localmind.worker.client import WorkerClient
from localmind.worker.loop import WorkerLoop


def test_worker_help_lists_run_command():
    parser = worker_main.build_parser()
    help_text = parser.format_help()
    assert "run" in help_text.lower()


def test_cmd_run_rejects_unpaired_worker(monkeypatch):
    monkeypatch.setattr(worker_main, "load_worker_config", lambda: None)
    args = argparse.Namespace(poll_interval=0.1, heartbeat_interval=0.1, max_backoff=0.1)
    assert worker_main.cmd_run(args) == 1


def test_worker_loop_completes_supported_task(monkeypatch):
    loop = WorkerLoop("http://example.com", "token", "worker-1")
    calls: list[str] = []

    def fake_request(self, path, method="GET", payload=None, timeout=10):
        calls.append(path)
        if path == "api/worker/heartbeat":
            return 200, {"status": "ok"}, None
        if path == "api/worker/claim":
            return 200, {"task": {"id": "task-1", "type": "noop", "payload": {"duration": 0.0}, "lease_seconds": 30}}, None
        if path == "api/worker/tasks/task-1/complete":
            return 200, {"status": "ok"}, None
        return 0, None, "unexpected"

    monkeypatch.setattr(WorkerClient, "request", fake_request)
    assert loop.run_once() is True
    assert "api/worker/claim" in calls
    assert "api/worker/tasks/task-1/complete" in calls


def test_worker_loop_reports_failure_for_invalid_task(monkeypatch):
    loop = WorkerLoop("http://example.com", "token", "worker-2")

    def fake_request(self, path, method="GET", payload=None, timeout=10):
        if path == "api/worker/claim":
            return 200, {"task": {"id": "task-2", "type": "unsupported", "payload": {}, "lease_seconds": 30}}, None
        if path == "api/worker/tasks/task-2/fail":
            return 200, {"status": "ok"}, None
        return 0, None, "unexpected"

    monkeypatch.setattr(WorkerClient, "request", fake_request)
    assert loop.run_once() is False
