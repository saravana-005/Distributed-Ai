from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    token_hash TEXT,
    revoked_at TEXT,
    last_seen TEXT,
    cpu_percent REAL,
    ram_total_mb REAL,
    ram_available_mb REAL,
    battery_percent REAL,
    battery_charging INTEGER,
    software_version TEXT,
    protocol_version INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS pairing_codes (
    id TEXT PRIMARY KEY,
    code TEXT,
    code_hash TEXT,
    worker_id TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    consumed_at TEXT,
    source_ip TEXT,
    worker_name TEXT,
    admin_url TEXT,
    FOREIGN KEY(worker_id) REFERENCES workers(id)
);

CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    storage_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    rows INTEGER NOT NULL DEFAULT 0,
    column_count INTEGER NOT NULL DEFAULT 0,
    columns_json TEXT NOT NULL DEFAULT '[]',
    validation_status TEXT NOT NULL DEFAULT 'pending',
    validation_summary TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    dataset_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cancelled INTEGER NOT NULL DEFAULT 0,
    total_tasks INTEGER NOT NULL DEFAULT 0,
    completed_tasks INTEGER NOT NULL DEFAULT 0,
    failed_tasks INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'noop',
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    state TEXT NOT NULL DEFAULT 'PENDING',
    assigned_worker_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_expires_at TEXT,
    completed_at TEXT,
    result TEXT,
    error TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id),
    FOREIGN KEY(assigned_worker_id) REFERENCES workers(id)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    job_id TEXT,
    worker_id TEXT,
    message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES jobs(id),
    FOREIGN KEY(worker_id) REFERENCES workers(id)
);
"""

_MIGRATIONS = [
    "ALTER TABLE workers ADD COLUMN token_hash TEXT",
    "ALTER TABLE workers ADD COLUMN revoked_at TEXT",
    "ALTER TABLE workers ADD COLUMN last_seen TEXT",
    "ALTER TABLE workers ADD COLUMN cpu_percent REAL",
    "ALTER TABLE workers ADD COLUMN ram_total_mb REAL",
    "ALTER TABLE workers ADD COLUMN ram_available_mb REAL",
    "ALTER TABLE workers ADD COLUMN battery_percent REAL",
    "ALTER TABLE workers ADD COLUMN battery_charging INTEGER",
    "ALTER TABLE workers ADD COLUMN software_version TEXT",
    "ALTER TABLE workers ADD COLUMN protocol_version INTEGER DEFAULT 1",
    "ALTER TABLE pairing_codes ADD COLUMN code TEXT",
    "ALTER TABLE pairing_codes ADD COLUMN code_hash TEXT",
    "ALTER TABLE pairing_codes ADD COLUMN consumed_at TEXT",
    "ALTER TABLE pairing_codes ADD COLUMN source_ip TEXT",
    "ALTER TABLE pairing_codes ADD COLUMN worker_name TEXT",
    "ALTER TABLE pairing_codes ADD COLUMN admin_url TEXT",
    "ALTER TABLE datasets ADD COLUMN storage_name TEXT DEFAULT ''",
    "ALTER TABLE datasets ADD COLUMN sha256 TEXT DEFAULT ''",
    "ALTER TABLE datasets ADD COLUMN size_bytes INTEGER DEFAULT 0",
    "ALTER TABLE datasets ADD COLUMN column_count INTEGER DEFAULT 0",
    "ALTER TABLE datasets ADD COLUMN columns_json TEXT DEFAULT '[]'",
    "ALTER TABLE datasets ADD COLUMN validation_status TEXT DEFAULT 'pending'",
    "ALTER TABLE datasets ADD COLUMN validation_summary TEXT DEFAULT '{}'",
    "ALTER TABLE jobs ADD COLUMN dataset_id TEXT",
    "ALTER TABLE jobs ADD COLUMN cancelled INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN total_tasks INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN completed_tasks INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN failed_tasks INTEGER DEFAULT 0",
    "ALTER TABLE tasks ADD COLUMN type TEXT DEFAULT 'noop'",
    "ALTER TABLE tasks ADD COLUMN payload TEXT DEFAULT '{}'",
    "ALTER TABLE tasks ADD COLUMN status TEXT DEFAULT 'queued'",
    "ALTER TABLE tasks ADD COLUMN state TEXT DEFAULT 'PENDING'",
    "ALTER TABLE tasks ADD COLUMN assigned_worker_id TEXT",
    "ALTER TABLE tasks ADD COLUMN attempts INTEGER DEFAULT 0",
    "ALTER TABLE tasks ADD COLUMN max_attempts INTEGER DEFAULT 3",
    "ALTER TABLE tasks ADD COLUMN lease_expires_at TEXT",
    "ALTER TABLE tasks ADD COLUMN completed_at TEXT",
    "ALTER TABLE tasks ADD COLUMN result TEXT",
    "ALTER TABLE tasks ADD COLUMN error TEXT",
]

_WRITE_LOCK = threading.RLock()


def _apply_schema_migrations(connection: sqlite3.Connection) -> None:
    for statement in _MIGRATIONS:
        try:
            connection.execute(statement)
        except sqlite3.OperationalError:
            pass


def open_database(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def database_connection(database_path: str | Path) -> Iterator[sqlite3.Connection]:
    connection = open_database(database_path)
    try:
        yield connection
    finally:
        connection.close()


def init_database(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    connection = open_database(path)
    with _WRITE_LOCK:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.executescript(SCHEMA_SQL)
            _apply_schema_migrations(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return connection
