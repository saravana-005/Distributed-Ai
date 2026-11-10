from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from localmind.admin.db import database_connection

DEFAULT_DB_PATH = Path("./data") / "localmind.db"
_PAIRING_PREFIX_LENGTH = 4
_PAIRING_SUFFIX_LENGTH = 5
_FAILED_ATTEMPTS: dict[str, list[float]] = {}
_FAILED_ATTEMPTS_LOCK = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _database_path(database_path: str | Path | None) -> Path:
    return Path(database_path) if database_path is not None else DEFAULT_DB_PATH


def generate_pairing_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    left = "".join(secrets.choice(alphabet) for _ in range(_PAIRING_PREFIX_LENGTH))
    right = "".join(secrets.choice(alphabet) for _ in range(_PAIRING_SUFFIX_LENGTH))
    return f"{left}-{right}"


def hash_pairing_code(code: str) -> str:
    normalized = (code or "").strip().upper().replace("-", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_worker_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_pairing_attempts(source_ip: str) -> list[float]:
    with _FAILED_ATTEMPTS_LOCK:
        return list(_FAILED_ATTEMPTS.get(source_ip, []))


def record_failed_pairing_attempt(source_ip: str) -> bool:
    now = time.time()
    with _FAILED_ATTEMPTS_LOCK:
        attempts = _FAILED_ATTEMPTS.setdefault(source_ip, [])
        attempts[:] = [ts for ts in attempts if ts > now - 60]
        attempts.append(now)
        return len(attempts) >= 5


def rate_limit_exceeded(source_ip: str) -> bool:
    now = time.time()
    with _FAILED_ATTEMPTS_LOCK:
        attempts = _FAILED_ATTEMPTS.setdefault(source_ip, [])
        attempts[:] = [ts for ts in attempts if ts > now - 60]
        return len(attempts) >= 5


def check_pairing_code(code: str) -> tuple[bool, str | None, str | None]:
    if not code or len(code.strip()) < 5:
        return False, "invalid", None
    normalized = code.strip().upper().replace("-", "")
    if len(normalized) != _PAIRING_PREFIX_LENGTH + _PAIRING_SUFFIX_LENGTH:
        return False, "invalid", None
    return True, None, normalized


def record_pairing_code(
    code: str,
    source_ip: str,
    worker_name: str | None = None,
    admin_url: str | None = None,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = _database_path(database_path)
    payload: dict[str, Any] = {
        "id": secrets.token_hex(16),
        "code_hash": hash_pairing_code(code),
        "expires_at": (_utc_now() + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_at": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_ip": source_ip,
        "worker_name": worker_name or "worker",
        "admin_url": admin_url,
    }
    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO pairing_codes (
                id, code_hash, expires_at, created_at, source_ip, worker_name, admin_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["id"],
                payload["code_hash"],
                payload["expires_at"],
                payload["created_at"],
                source_ip,
                worker_name or "worker",
                admin_url,
            ),
        )
    return payload


def create_worker_record(name: str) -> tuple[str, str]:
    worker_id = secrets.token_hex(12)
    token = secrets.token_urlsafe(32)
    return worker_id, token


def redeem_pairing_code(
    code: str,
    worker_name: str | None,
    source_ip: str,
    admin_url: str | None = None,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = _database_path(database_path)
    normalized = (code or "").strip().upper()
    code_hash = hash_pairing_code(normalized)
    now = _utc_now()
    with database_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                """
                SELECT id, code, code_hash, expires_at, consumed_at, worker_id, source_ip
                FROM pairing_codes
                WHERE COALESCE(code_hash, code) = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (code_hash,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise ValueError("unknown_pairing_code")
            expires_at = row["expires_at"]
            if expires_at is None:
                conn.rollback()
                raise ValueError("expired_pairing_code")
            expires_dt = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if expires_dt < now:
                conn.rollback()
                raise ValueError("expired_pairing_code")
            if row["consumed_at"] is not None or row["worker_id"] is not None:
                conn.rollback()
                raise ValueError("used_pairing_code")

            name_candidate = (worker_name or "worker").strip() or "worker"
            name_value = name_candidate[:64]
            try:
                conn.execute(
                    """
                    INSERT INTO workers (
                        id, name, status, created_at, updated_at, token_hash, last_seen, revoked_at,
                        protocol_version
                    ) VALUES (?, ?, 'online', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        secrets.token_hex(12),
                        name_value,
                        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        None,
                        None,
                        None,
                        1,
                    ),
                )
            except sqlite3.IntegrityError:
                suffix = secrets.token_hex(4)
                name_value = f"{name_candidate[:60]}-{suffix}"
                conn.execute(
                    """
                    INSERT INTO workers (
                        id, name, status, created_at, updated_at, token_hash, last_seen, revoked_at,
                        protocol_version
                    ) VALUES (?, ?, 'online', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        secrets.token_hex(12),
                        name_value,
                        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        None,
                        None,
                        None,
                        1,
                    ),
                )
            worker_id = conn.execute("SELECT id FROM workers WHERE name = ? ORDER BY created_at DESC LIMIT 1", (name_value,)).fetchone()[0]
            worker_token = secrets.token_urlsafe(32)
            token_hash = hash_worker_token(worker_token)
            conn.execute(
                "UPDATE workers SET token_hash = ?, updated_at = ? WHERE id = ?",
                (token_hash, now.strftime("%Y-%m-%dT%H:%M:%SZ"), worker_id),
            )
            conn.execute(
                "UPDATE pairing_codes SET consumed_at = ?, worker_id = ?, source_ip = ?, code_hash = COALESCE(code_hash, code) WHERE id = ?",
                (now.strftime("%Y-%m-%dT%H:%M:%SZ"), worker_id, source_ip, row["id"]),
            )
            conn.commit()
            return {
                "worker_id": worker_id,
                "worker_token": worker_token,
                "protocol_version": 1,
                "admin_url": admin_url,
                "name": name_value,
            }
        except Exception:
            conn.rollback()
            raise


def get_worker_list(database_path: str | Path | None = None) -> list[dict[str, Any]]:
    db_path = _database_path(database_path)
    with database_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, name, status, created_at, updated_at, last_seen, cpu_percent, ram_total_mb,
                   ram_available_mb, battery_percent, battery_charging, software_version,
                   protocol_version, revoked_at, token_hash
            FROM workers ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_worker_by_id(worker_id: str, database_path: str | Path | None = None) -> dict[str, Any] | None:
    db_path = _database_path(database_path)
    with database_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, name, status, created_at, updated_at, last_seen, cpu_percent, ram_total_mb,
                   ram_available_mb, battery_percent, battery_charging, software_version,
                   protocol_version, revoked_at, token_hash
            FROM workers WHERE id = ?
            """,
            (worker_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def get_worker_by_token(token: str, database_path: str | Path | None = None) -> dict[str, Any] | None:
    db_path = _database_path(database_path)
    token_hash = hash_worker_token(token)
    with database_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, name, status, created_at, updated_at, last_seen, cpu_percent, ram_total_mb,
                   ram_available_mb, battery_percent, battery_charging, software_version,
                   protocol_version, revoked_at, token_hash
            FROM workers WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    return dict(row) if row is not None else None


def revoke_worker(worker_id: str, database_path: str | Path | None = None) -> bool:
    db_path = _database_path(database_path)
    now = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    with database_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE workers SET revoked_at = ?, status = 'revoked', updated_at = ? WHERE id = ?",
            (now, now, worker_id),
        )
        changed = cursor.rowcount > 0
    return changed


def worker_is_online(last_seen: str | None) -> bool:
    if not last_seen:
        return False
    try:
        seen = datetime.strptime(last_seen, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - seen).total_seconds() <= 30


def database_worker_status(worker_id: str, database_path: str | Path | None = None) -> dict[str, Any]:
    row = get_worker_by_id(worker_id, database_path=database_path)
    if row is None:
        return {"worker_id": worker_id, "status": "unknown"}
    return {
        "worker_id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "online": worker_is_online(row.get("last_seen")),
        "last_seen": row.get("last_seen"),
        "cpu_percent": row.get("cpu_percent"),
        "ram_total_mb": row.get("ram_total_mb"),
        "ram_available_mb": row.get("ram_available_mb"),
        "battery_percent": row.get("battery_percent"),
        "battery_charging": row.get("battery_charging"),
        "software_version": row.get("software_version"),
    }

