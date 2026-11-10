from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from itsdangerous import BadData, URLSafeTimedSerializer

DEFAULT_SECRET_FILENAME = "admin-secret.key"
DEFAULT_ADMIN_FILENAME = "admin.json"


def _secret_path(secret_path: str | Path | None = None) -> Path:
    if secret_path is None:
        secret_path = Path("./data") / DEFAULT_SECRET_FILENAME
    return Path(secret_path)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_secret(secret_path: str | Path | None = None) -> str:
    path = _secret_path(secret_path)
    _ensure_parent(path)
    if not path.exists():
        secret = secrets.token_urlsafe(32)
        path.write_text(secret, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return secret
    return path.read_text(encoding="utf-8")


def generate_admin_secret(secret_path: str | Path | None = None) -> str:
    return _read_secret(secret_path)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    return f"$scrypt${salt.hex()}${digest.hex()}"


def is_valid_password(password: str, encoded: str) -> bool:
    if not encoded or not encoded.startswith("$scrypt$"):
        return False
    prefix, salt_hex, digest_hex = encoded.split("$")[1:]
    if prefix != "scrypt":
        return False
    salt = bytes.fromhex(salt_hex)
    expected = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    return expected.hex() == digest_hex


def initialize_admin_account(data_dir: str | Path) -> str | None:
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    credentials_path = data_path / DEFAULT_ADMIN_FILENAME
    if credentials_path.exists():
        return None

    password = secrets.token_urlsafe(18)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    payload: dict[str, Any] = {
        "username": "admin",
        "salt": salt.hex(),
        "password_hash": f"$scrypt${salt.hex()}${digest.hex()}",
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    credentials_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(credentials_path, 0o600)
    except OSError:
        pass
    print(f"Initial admin password: {password}")
    return password


def load_admin_credentials(data_dir: str | Path) -> dict[str, Any] | None:
    credentials_path = Path(data_dir) / DEFAULT_ADMIN_FILENAME
    if not credentials_path.exists():
        return None
    content = credentials_path.read_text(encoding="utf-8")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def verify_admin_password(data_dir: str | Path, password: str) -> bool:
    payload = load_admin_credentials(data_dir)
    if not payload:
        return False
    return is_valid_password(password, payload.get("password_hash", ""))


def create_session_cookie(password: str, secret_path: str | Path | None = None) -> str:
    serializer = URLSafeTimedSerializer(_read_secret(secret_path))
    return serializer.dumps({"password": password})


def verify_session_cookie(token: str, secret_path: str | Path | None = None) -> str | None:
    serializer = URLSafeTimedSerializer(_read_secret(secret_path))
    try:
        payload = serializer.loads(token)
    except (BadData, TypeError, ValueError):
        return None
    if isinstance(payload, dict):
        password = payload.get("password")
        if isinstance(password, str):
            return password
    return None
