# Dataset management

LocalMind stores CSV datasets under the admin’s private `data_dir` and records metadata in SQLite. The admin API accepts only validated CSV uploads and rejects unsafe or malformed files before they are stored.

## Supported format

- File type: CSV only.
- Content type: `text/csv` or equivalent CSV upload.
- Name requirement: basename must not contain path traversal elements or unsafe separators.
- Size limit: default 50 MiB per dataset.
- Row requirement: at least one data row after the header.
- Header requirement: non-empty column names; duplicate names are rejected.

## Validation behavior

The upload path checks:

1. File extension is `.csv`.
2. File name resolves safely within the private data directory.
3. File size is below the configured dataset cap.
4. Header row is present and contains unique, non-empty columns.
5. Rows parse cleanly into the same number of columns as the header.
6. The content hash is generated and persisted alongside the metadata.

## Storage rules

- Files are written under the configured admin `data_dir`.
- Public static assets are not used for dataset storage.
- Metadata includes `id`, `name`, `size_bytes`, `sha256`, `rows`, `columns`, and `created_at`.

## Job linkage and delete policy

A dataset cannot be deleted while it remains referenced by an active job. The admin API returns HTTP 409 in that case. This prevents accidental data loss during a running training or evaluation job.

## API summary

- `POST /api/datasets`: upload CSV
- `GET /api/datasets`: list datasets
- `GET /api/datasets/{dataset_id}`: fetch one dataset record
- `DELETE /api/datasets/{dataset_id}`: remove a dataset if it is unreferenced
