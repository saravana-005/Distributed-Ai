# LocalMind

LocalMind is a LAN-based distributed computing system designed to distribute independent machine-learning workloads across trusted laptops.

## Phase 0 status

Based on the recorded Phase 0 results in this repository:

- Spike A — Packaging: PASS
- Spike C — ML benchmark: PASS
- Spike B — Connectivity: NEEDS REVIEW (not executed in this Linux environment because no second trusted laptop or hotspot path was available)

The Phase 0 benchmark measured a 20,000-row RandomForest cross-validation task at 17.374 seconds with 0.9508 mean accuracy, which exceeds the target threshold and is large enough for initial distribution.

## Phase 1

Phase 1 creates the project foundation and admin shell: a Python package layout, typed configuration, SQLite initialization, first-run admin credential handling, signed session cookies, and a minimal admin dashboard with LAN URL detection and health checks.

## Install Admin dependencies

```bash
pip install -e ".[admin,dev]"
```

## Run tests

```bash
pytest -q
```

## Run lint

```bash
ruff check .
```

## Launch the Admin server

```bash
python -m localmind.admin
```

The first launch prints a one-time initial admin password. Use that password to log in at:

```text
http://127.0.0.1:8000/login
```

## Launch the worker placeholder

```bash
python -m localmind.worker --help
```

## Local dashboard and LAN URL check

Open the local dashboard:

```text
http://127.0.0.1:8000/
```

The dashboard shows the localhost URL and any private LAN IPv4 addresses detected via the local network interfaces. LAN access is only intended for trusted local networks; the Phase 1 HTTP mode is not suitable for untrusted networks.

## Phase 1 limitations

The current Phase 1 implementation intentionally does not include:

- worker pairing
- worker authentication tokens
- task claiming or scheduling
- dataset upload
- ML job execution
- production TLS hardening
- federated learning features

## Phase 4 dataset management

Phase 4 adds secure CSV dataset uploads for the admin laptop. Datasets are validated before registration, stored under the private data directory, and linked to jobs by dataset ID rather than by user-supplied paths.

Supported behavior:

- Upload and validate CSV files only.
- Enforce a 50 MiB default upload cap and a 500-column maximum.
- Store datasets under the private data directory, never in a public static directory.
- Record SHA-256, size, row count, column count, and validation status.
- Reject malformed CSV, empty files, duplicate/empty column names, and unsafe filenames.
- Prevent deleting a dataset that is still referenced by an active job.

API operations supported:

- `POST /api/datasets`
- `GET /api/datasets`
- `GET /api/datasets/{dataset_id}`
- `DELETE /api/datasets/{dataset_id}`

See [docs/datasets.md](docs/datasets.md) for the full policy and validation rules.

## Current network note

Phase 1 uses plain HTTP for the local admin shell and LAN URL display only. TLS and stronger hardening belong to a later phase.
