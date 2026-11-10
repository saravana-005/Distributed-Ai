from __future__ import annotations

import argparse
import json
import signal
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from localmind.common.protocol import PROTOCOL_VERSION
from localmind.common.version import VERSION
from localmind.worker.config import (
    clear_worker_config,
    load_worker_config,
    save_worker_config,
    validate_admin_url,
)
from localmind.worker.loop import WorkerLoop


def _http_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None, token: str | None = None, timeout: int = 10) -> tuple[int, dict[str, Any] | None, str | None]:
    headers = {"X-LocalMind-Protocol": str(PROTOCOL_VERSION)}
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method=method)
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


def _parse_admin_url(value: str) -> str:
    cleaned = validate_admin_url(value)
    return cleaned.rstrip("/")


def _worker_status_output(config: dict[str, str]) -> tuple[int, dict[str, Any] | None, str | None]:
    worker_url = f"{config['admin_url']}/api/worker/status"
    return _http_json(worker_url, method="GET", token=config["worker_token"], timeout=10)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m localmind.worker",
        description="LocalMind worker client",
    )
    parser.add_argument("--version", action="store_true", help="Display version information.")
    subparsers = parser.add_subparsers(dest="command")

    pair_parser = subparsers.add_parser("pair", help="Pair with an admin instance using a one-time code")
    pair_parser.add_argument("--admin", required=True, help="Admin URL such as http://192.168.1.10:8000")
    pair_parser.add_argument("--code", required=True, help="Single-use pairing code")
    pair_parser.add_argument("--name", default="worker", help="Worker name")

    status_parser = subparsers.add_parser("status", help="Show configured worker information")
    status_parser.add_argument("--json", action="store_true", help="Emit JSON output")

    run_parser = subparsers.add_parser("run", help="Run the worker loop and process queued tasks")
    run_parser.add_argument("--poll-interval", type=float, default=1.0, help="Seconds between task polls")
    run_parser.add_argument("--heartbeat-interval", type=float, default=30.0, help="Seconds between admin heartbeats")
    run_parser.add_argument("--max-backoff", type=float, default=30.0, help="Maximum exponential backoff seconds")

    unpair_parser = subparsers.add_parser("unpair", help="Remove local credentials and try a remote revocation")
    unpair_parser.add_argument("--force", action="store_true", help="Skip interactive confirmation")

    return parser


def cmd_pair(args: argparse.Namespace) -> int:
    admin_url = _parse_admin_url(args.admin)
    existing = load_worker_config()
    if existing is not None:
        print("Worker is already configured. Use 'unpair' before pairing again.")
        return 1
    payload = {"code": args.code.strip(), "worker_name": args.name.strip() or "worker"}
    status, body, error = _http_json(f"{admin_url}/api/pair", method="POST", payload=payload)
    if status != 200:
        message = body.get("detail") if isinstance(body, dict) else error or "Pairing request failed"
        print(f"Pairing failed: {message}")
        return 1
    if not isinstance(body, dict):
        print("Pairing response was invalid.")
        return 1
    worker_id = body.get("worker_id")
    worker_token = body.get("worker_token")
    if not worker_id or not worker_token:
        print("Pairing response did not include a valid worker identity or token.")
        return 1
    save_worker_config(admin_url, worker_id, worker_token)
    print(f"Worker paired with admin at {admin_url}.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_worker_config()
    if config is None:
        print("No worker credentials are configured.")
        return 0
    print(f"Worker ID: {config['worker_id']}")
    print(f"Admin URL: {config['admin_url']}")
    status, body, error = _worker_status_output(config)
    if status == 200 and isinstance(body, dict):
        print(f"Online: {body.get('online', False)}")
        if body.get('last_seen'):
            print(f"Last seen: {body['last_seen']}")
        return 0
    if status in (0, 401, 403, 404):
        print("Admin is reachable but worker status is unavailable or untrusted.")
    else:
        print(f"Admin status check failed: {error or 'unknown error'}")
    return 0


def cmd_unpair(args: argparse.Namespace) -> int:
    config = load_worker_config()
    if config is None:
        print("No worker credentials are configured.")
        return 0
    if not args.force:
        answer = input("Delete local worker credentials and attempt remote revocation? [y/N]: ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Unpair cancelled.")
            return 0
    clear_worker_config()
    admin_url = config["admin_url"]
    worker_url = f"{admin_url}/api/worker/revoke"
    status, _body, error = _http_json(worker_url, method="POST", payload={"worker_id": config["worker_id"]}, token=config["worker_token"])
    if status == 200:
        print("Local credentials removed and remote revocation succeeded.")
        return 0
    if status in (0, 401, 403, 404):
        print("Local credentials removed. Remote revocation could not be confirmed; the admin may still need attention.")
        return 0
    print(f"Local credentials removed. Remote revocation status: {error or 'unknown'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_worker_config()
    if config is None:
        print("No worker credentials are configured.")
        return 1
    loop = WorkerLoop(config["admin_url"], config["worker_token"], config.get("worker_id"))
    stop_event = threading.Event()

    def _handle_shutdown(signum: int, frame: Any) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    print(f"Starting worker runtime for {config['worker_id']} at {config['admin_url']}")
    try:
        return loop.run_forever(
            poll_interval=max(0.1, float(args.poll_interval)),
            heartbeat_interval=max(1.0, float(args.heartbeat_interval)),
            max_backoff=max(1.0, float(args.max_backoff)),
            stop_event=stop_event,
        )
    except KeyboardInterrupt:
        print("Worker shutdown requested.")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"localmind {VERSION}")
        return 0
    if args.command == "pair":
        return cmd_pair(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "unpair":
        return cmd_unpair(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
