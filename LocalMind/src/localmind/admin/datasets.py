from __future__ import annotations

import csv
import hashlib
import io
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localmind.admin.db import database_connection

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_COLUMNS = 500


def dataset_storage_root(data_dir: str | Path) -> Path:
    root = Path(data_dir).expanduser() / "datasets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize_display_name(filename: str) -> str:
    if not filename or filename.strip() == "":
        raise ValueError("Dataset filename is required")
    candidate = Path(filename).name
    if candidate in {"", ".", ".."}:
        raise ValueError("Invalid dataset filename")
    if "/" in filename or "\\" in filename:
        raise ValueError("Dataset filename must not contain path separators")
    if not candidate.lower().endswith(".csv"):
        raise ValueError("Only CSV files are supported")
    return candidate


def _validate_csv_bytes(raw_bytes: bytes, *, max_columns: int = DEFAULT_MAX_COLUMNS) -> tuple[list[str], int, int, str]:
    if len(raw_bytes) == 0:
        raise ValueError("Dataset file is empty")
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Dataset must be UTF-8 or UTF-8 with BOM") from exc
    if not text.strip():
        raise ValueError("Dataset file is empty")

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("CSV content is empty")
    header = rows[0]
    if not header or any((value or "").strip() == "" for value in header):
        raise ValueError("CSV header contains empty column names")
    normalized = [value.strip() for value in header]
    if len(normalized) > max_columns:
        raise ValueError(f"CSV exceeds the maximum column count of {max_columns}")
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in normalized:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"Duplicate column names are not allowed: {', '.join(sorted(set(duplicates))[:5])}")
    if len(rows) < 2:
        raise ValueError("CSV must contain at least one data row")
    expected_width = len(normalized)
    for index, row in enumerate(rows[1:], start=2):
        if len(row) != expected_width:
            raise ValueError(f"Row {index} does not match the header width")
    return normalized, len(rows) - 1, expected_width, hashlib.sha256(raw_bytes).hexdigest()


def register_dataset(
    data_dir: str | Path,
    *,
    filename: str,
    file_bytes: bytes,
    max_upload_size_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    max_columns: int = DEFAULT_MAX_COLUMNS,
) -> dict[str, Any]:
    if not isinstance(file_bytes, (bytes, bytearray)):
        raise TypeError("Uploaded dataset is not valid binary content")
    raw_bytes = bytes(file_bytes)
    if len(raw_bytes) > max_upload_size_bytes:
        raise ValueError(f"Dataset exceeds the maximum upload size of {max_upload_size_bytes} bytes")

    safe_name = _normalize_display_name(filename)
    columns, row_count, column_count, sha256_hex = _validate_csv_bytes(raw_bytes, max_columns=max_columns)

    dataset_id = secrets.token_hex(12)
    storage_root = dataset_storage_root(data_dir)
    storage_filename = f"{dataset_id}.csv"
    target_path = storage_root / storage_filename
    temp_path = storage_root / f".{dataset_id}.tmp"

    resolved_root = storage_root.resolve()
    if not target_path.resolve().is_relative_to(resolved_root):
        raise ValueError("Unsafe dataset storage path")

    try:
        temp_path.write_bytes(raw_bytes)
        os.replace(temp_path, target_path)
    except OSError as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise ValueError("Unable to store dataset file") from exc

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = {
        "id": dataset_id,
        "name": safe_name,
        "storage_name": storage_filename,
        "path": f"datasets/{storage_filename}",
        "sha256": sha256_hex,
        "size_bytes": len(raw_bytes),
        "rows": row_count,
        "column_count": column_count,
        "columns": columns,
        "validation_status": "valid",
        "validation_summary": {"rows": row_count, "columns": column_count, "sha256": sha256_hex},
    }

    db_path = Path(data_dir) / "localmind.db"
    try:
        with database_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO datasets (
                    id, name, path, storage_name, sha256, size_bytes, rows, column_count,
                    columns_json, validation_status, validation_summary, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    safe_name,
                    metadata["path"],
                    storage_filename,
                    sha256_hex,
                    len(raw_bytes),
                    row_count,
                    column_count,
                    __import__("json").dumps(columns),
                    "valid",
                    __import__("json").dumps(metadata["validation_summary"]),
                    now,
                    now,
                ),
            )
            conn.commit()
    except Exception:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise
    return metadata


def list_datasets(data_dir: str | Path) -> list[dict[str, Any]]:
    db_path = Path(data_dir) / "localmind.db"
    with database_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, path, storage_name, sha256, size_bytes, rows, column_count, columns_json, validation_status, validation_summary, created_at, updated_at FROM datasets ORDER BY created_at DESC"
        ).fetchall()
    datasets: list[dict[str, Any]] = []
    for row in rows:
        datasets.append({
            "id": row["id"],
            "name": row["name"],
            "path": row["path"],
            "storage_name": row["storage_name"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "rows": row["rows"],
            "column_count": row["column_count"],
            "columns": __import__("json").loads(row["columns_json"] or "[]"),
            "validation_status": row["validation_status"],
            "validation_summary": __import__("json").loads(row["validation_summary"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return datasets


def get_dataset(data_dir: str | Path, dataset_id: str) -> dict[str, Any] | None:
    db_path = Path(data_dir) / "localmind.db"
    with database_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, name, path, storage_name, sha256, size_bytes, rows, column_count, columns_json, validation_status, validation_summary, created_at, updated_at FROM datasets WHERE id = ?",
            (dataset_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "path": row["path"],
        "storage_name": row["storage_name"],
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "rows": row["rows"],
        "column_count": row["column_count"],
        "columns": __import__("json").loads(row["columns_json"] or "[]"),
        "validation_status": row["validation_status"],
        "validation_summary": __import__("json").loads(row["validation_summary"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def dataset_file_path(data_dir: str | Path, dataset_id: str) -> Path:
    dataset = get_dataset(data_dir, dataset_id)
    if dataset is None:
        raise ValueError("dataset_not_found")
    path = (Path(data_dir) / dataset["path"]).resolve()
    base = (Path(data_dir) / "datasets").resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ValueError("dataset_path_invalid") from exc
    return path


def ensure_dataset_valid(data_dir: str | Path, dataset_id: str) -> dict[str, Any]:
    dataset = get_dataset(data_dir, dataset_id)
    if dataset is None:
        raise ValueError("dataset_not_found")
    if dataset.get("validation_status") != "valid":
        raise ValueError("dataset_invalid")
    return dataset


def delete_dataset(data_dir: str | Path, dataset_id: str) -> bool:
    db_path = Path(data_dir) / "localmind.db"
    with database_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, path FROM datasets WHERE id = ?",
            (dataset_id,),
        ).fetchone()
        if row is None:
            return False
        active_jobs = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE dataset_id = ? AND status IN ('queued', 'running')",
            (dataset_id,),
        ).fetchone()[0]
        if active_jobs:
            raise ValueError("dataset_in_use")
        file_path = (Path(data_dir) / row["path"]).resolve()
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
        conn.commit()
        return True
