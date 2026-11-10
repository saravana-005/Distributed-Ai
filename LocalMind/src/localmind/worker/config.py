from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CONFIG_FILENAME = "worker.json"


def default_config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        return Path(appdata) / "LocalMind" / DEFAULT_CONFIG_FILENAME
    return Path.home() / ".config" / "localmind" / DEFAULT_CONFIG_FILENAME


def validate_admin_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Admin URL must use http or https")
    if not parsed.netloc:
        raise ValueError("Admin URL must include a host and port")
    return value.rstrip("/")


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass


def load_worker_config(path: str | Path | None = None) -> dict[str, str] | None:
    config_path = Path(path) if path else default_config_path()
    if not config_path.exists():
        return None
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("Worker config must be a JSON object")
    validate_worker_config(data)
    return data


def validate_worker_config(data: dict[str, str]) -> dict[str, str]:
    admin_url = data.get("admin_url")
    worker_id = data.get("worker_id")
    worker_token = data.get("worker_token")
    if not isinstance(admin_url, str) or not admin_url.strip():
        raise ValueError("admin_url is required")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ValueError("worker_id is required")
    if not isinstance(worker_token, str) or not worker_token.strip():
        raise ValueError("worker_token is required")
    return {
        "admin_url": validate_admin_url(admin_url),
        "worker_id": worker_id.strip(),
        "worker_token": worker_token.strip(),
    }


def save_worker_config(
    admin_url: str,
    worker_id: str,
    worker_token: str,
    path: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    config_path = Path(path) if path else default_config_path()
    config_path = config_path.expanduser()
    if config_path.exists() and not overwrite:
        raise FileExistsError(f"Worker config already exists at {config_path}")
    normalized = validate_worker_config({
        "admin_url": admin_url,
        "worker_id": worker_id,
        "worker_token": worker_token,
    })
    _ensure_dir(config_path)
    config_path.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(config_path, 0o600)
    except OSError:
        pass
    return config_path


def clear_worker_config(path: str | Path | None = None) -> bool:
    config_path = Path(path) if path else default_config_path()
    if not config_path.exists():
        return False
    config_path.unlink()
    return True
