import sqlite3

import pytest

from localmind.admin.db import init_database, open_database


def test_database_initialization(tmp_path):
    db_path = tmp_path / "localmind.db"
    conn = init_database(db_path)
    assert conn is not None

    with sqlite3.connect(db_path) as db:
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {row[0] for row in tables}
        assert {"workers", "pairing_codes", "datasets", "jobs", "tasks", "events"}.issubset(names)


def test_database_idempotent_setup(tmp_path):
    db_path = tmp_path / "localmind.db"
    init_database(db_path)
    init_database(db_path)
    with sqlite3.connect(db_path) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='workers'"
        ).fetchone()[0]
        assert count == 1


def test_database_wal_mode(tmp_path):
    db_path = tmp_path / "localmind.db"
    init_database(db_path)
    with sqlite3.connect(db_path) as db:
        journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode.lower() == "wal"


def test_database_foreign_keys_enabled(tmp_path):
    db_path = tmp_path / "localmind.db"
    init_database(db_path)
    with open_database(db_path) as db:
        pragma = db.execute("PRAGMA foreign_keys").fetchone()[0]
        assert pragma == 1


def test_database_transaction_rollback(tmp_path):
    db_path = tmp_path / "localmind.db"
    init_database(db_path)
    with open_database(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO workers (id, name, status, created_at) VALUES (?, ?, ?, datetime('now'))", ("row-1", "alpha", "ready"))
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM workers WHERE id = ?", ("row-1",)).fetchone()[0] == 0


def test_foreign_key_constraint_behavior(tmp_path):
    db_path = tmp_path / "localmind.db"
    init_database(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO tasks (id, job_id, status, created_at) VALUES (?, ?, ?, datetime('now'))",
                ("task-1", "missing-job", "queued",),
            )
