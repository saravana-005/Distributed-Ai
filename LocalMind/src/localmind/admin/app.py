from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

import psutil
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict, Field, field_validator

from localmind.admin.auth import (
    create_session_cookie,
    initialize_admin_account,
    verify_admin_password,
    verify_session_cookie,
)
from localmind.admin.config import AdminConfig
from localmind.admin.datasets import (
    delete_dataset,
    ensure_dataset_valid,
    get_dataset,
    list_datasets,
    register_dataset,
)
from localmind.admin.db import database_connection, init_database
from localmind.admin.jobs import create_demo_job
from localmind.admin.netinfo import detect_lan_urls
from localmind.admin.pairing import (
    database_worker_status,
    generate_pairing_code,
    get_worker_by_token,
    get_worker_list,
    hash_pairing_code,
    rate_limit_exceeded,
    record_failed_pairing_attempt,
    redeem_pairing_code,
    revoke_worker,
    worker_is_online,
)
from localmind.admin.queue import (
    cancel_job,
    claim_task,
    complete_task,
    create_job,
    extend_task_lease,
    fail_task,
    get_job_progress,
    recover_expired_leases,
)
from localmind.common.protocol import PROTOCOL_VERSION
from localmind.common.version import VERSION

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class PairingRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(..., min_length=5, max_length=32)
    worker_name: str | None = Field(default=None, max_length=128)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("pairing code is required")
        return cleaned


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    ram_total_mb: float | None = Field(default=None, ge=0, le=2_000_000)
    ram_available_mb: float | None = Field(default=None, ge=0, le=2_000_000)
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    battery_charging: bool | None = None
    software_version: str | None = Field(default=None, max_length=64)


class JobTaskSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = Field(default="noop", min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="demo-job", min_length=1, max_length=128)
    dataset_id: str | None = Field(default=None, min_length=1, max_length=128)
    tasks: list[JobTaskSpec] | None = Field(default=None)
    task_count: int = Field(default=1, ge=1, le=200)
    task_type: str = Field(default="noop", min_length=1, max_length=64)
    duration_seconds: float = Field(default=1.0, ge=0, le=600)


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lease_seconds: int | None = Field(default=None, ge=0, le=300)


class CompleteTaskRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    result: dict[str, Any] = Field(default_factory=dict)


class FailTaskRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: str = Field(default="worker_failed", min_length=1, max_length=2048)


def create_app(config: AdminConfig | None = None) -> FastAPI:
    config = config or AdminConfig()
    data_dir = Path(config.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    init_database(data_dir / "localmind.db")

    generated_password = initialize_admin_account(data_dir)

    app = FastAPI(title="LocalMind Admin")
    app.state.config = config
    app.state.admin_password = generated_password
    app.state.csrf_token = secrets.token_urlsafe(16)
    app.state.generated_pairing_code = None
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    template_env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    def render_template(name: str, **context: object) -> HTMLResponse:
        content = template_env.get_template(name).render(**context)
        return HTMLResponse(content=content)

    def _validate_csrf(form_data: dict[str, str]) -> bool:
        token = form_data.get("csrf_token")
        if token is None:
            return True
        return token == app.state.csrf_token

    def _authenticated_user(request: Request) -> str | None:
        cookie_value = request.cookies.get("localmind_session")
        if not cookie_value:
            return None
        return verify_session_cookie(cookie_value, config.secret_path)

    def _require_protocol(request: Request, *, allow_missing: bool = False) -> None:
        protocol_value = request.headers.get("X-LocalMind-Protocol")
        if protocol_value is None:
            if allow_missing:
                return
            raise HTTPException(status_code=426, detail="Missing X-LocalMind-Protocol header")
        if str(protocol_value).strip() != str(PROTOCOL_VERSION):
            raise HTTPException(
                status_code=426,
                detail=f"Incompatible protocol version: expected {PROTOCOL_VERSION}",
            )

    def _admin_authorized(request: Request) -> bool:
        if _authenticated_user(request):
            return True
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            token = header.split(" ", 1)[1].strip()
            return bool(token) and token == str(app.state.admin_password)
        return False

    def _worker_authorized(request: Request) -> dict[str, Any]:
        auth_header = request.headers.get("Authorization", "")
        scheme, sep, token = auth_header.partition(" ")
        if sep == "" or scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Unauthorized")
        worker = get_worker_by_token(token, database_path=str(data_dir / "localmind.db"))
        if worker is None:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if worker.get("revoked_at"):
            raise HTTPException(status_code=403, detail="Worker revoked")
        return worker

    @app.get("/")
    async def index(request: Request) -> RedirectResponse:
        if _authenticated_user(request):
            return RedirectResponse("/dashboard", status_code=303)
        return RedirectResponse("/login", status_code=303)

    @app.get("/login")
    async def login_page(request: Request) -> HTMLResponse:
        return render_template(
            "login.html",
            request=request,
            csrf_token=app.state.csrf_token,
            error="",
        )

    @app.post("/login")
    async def login_post(
        request: Request,
        password: str = Form(...),
        csrf_token: str | None = Form(default=None),
    ) -> object:
        if csrf_token is not None and not _validate_csrf({"csrf_token": csrf_token}):
            return render_template(
                "login.html",
                request=request,
                csrf_token=app.state.csrf_token,
                error="Invalid form token.",
            )

        if not verify_admin_password(data_dir, password):
            return render_template(
                "login.html",
                request=request,
                csrf_token=app.state.csrf_token,
                error="Incorrect password.",
            )

        response = RedirectResponse("/dashboard", status_code=303)
        response.set_cookie(
            "localmind_session",
            create_session_cookie(password, config.secret_path),
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return response

    @app.post("/logout")
    async def logout_post(
        request: Request,
        csrf_token: str | None = Form(default=None),
    ) -> RedirectResponse:
        if csrf_token is not None and not _validate_csrf({"csrf_token": csrf_token}):
            return RedirectResponse("/login", status_code=303)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("localmind_session", path="/")
        return response

    @app.post("/dashboard/pair")
    async def dashboard_pair(
        request: Request,
        csrf_token: str | None = Form(default=None),
    ) -> RedirectResponse:
        if not _authenticated_user(request):
            return RedirectResponse("/login", status_code=303)
        if csrf_token is not None and not _validate_csrf({"csrf_token": csrf_token}):
            return RedirectResponse("/dashboard", status_code=303)

        code = generate_pairing_code()
        app.state.generated_pairing_code = code
        code_hash = hash_pairing_code(code)
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        with database_connection(data_dir / "localmind.db") as conn:
            conn.execute(
                """
                INSERT INTO pairing_codes (
                    id, code, code_hash, expires_at, created_at, source_ip, worker_name, admin_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    secrets.token_hex(12),
                    code_hash,
                    code_hash,
                    expires_at,
                    created_at,
                    "dashboard",
                    "admin",
                    f"http://{config.host}:{config.port}",
                ),
            )
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/dashboard")
    async def dashboard(request: Request) -> HTMLResponse:
        session_password = _authenticated_user(request)
        if not session_password:
            return RedirectResponse("/login", status_code=303)

        localhost_url = f"http://127.0.0.1:{config.port}"
        try:
            lan_urls = detect_lan_urls(psutil.net_if_addrs(), port=config.port)
        except (OSError, TypeError, ValueError):
            lan_urls = []

        workers = []
        for worker in get_worker_list(str(data_dir / "localmind.db")):
            worker["online"] = worker_is_online(worker.get("last_seen"))
            workers.append(worker)

        return render_template(
            "dashboard.html",
            request=request,
            version=VERSION,
            protocol_version=PROTOCOL_VERSION,
            admin_status="Ready",
            localhost_url=localhost_url,
            lan_urls=lan_urls,
            workers=workers,
            generated_pairing_code=app.state.generated_pairing_code,
            csrf_token=app.state.csrf_token,
            admin_email="admin@localmind",
        )

    @app.post("/api/pair")
    async def pair_request(request: Request, payload: PairingRequest) -> dict[str, Any]:
        _require_protocol(request)
        source_ip = request.client.host if request.client else "unknown"
        if rate_limit_exceeded(source_ip):
            raise HTTPException(status_code=429, detail="Too many failed pairing attempts.")
        try:
            result = redeem_pairing_code(
                payload.code,
                payload.worker_name,
                source_ip,
                str(request.base_url).rstrip("/"),
                database_path=str(data_dir / "localmind.db"),
            )
            return {
                "worker_id": result["worker_id"],
                "worker_token": result["worker_token"],
                "protocol_version": PROTOCOL_VERSION,
                "admin_url": result["admin_url"],
            }
        except ValueError as exc:
            record_failed_pairing_attempt(source_ip)
            message = str(exc)
            if message == "unknown_pairing_code":
                raise HTTPException(status_code=404, detail="Unknown pairing code.")
            if message == "expired_pairing_code":
                raise HTTPException(status_code=410, detail="Pairing code expired.")
            if message == "used_pairing_code":
                raise HTTPException(status_code=409, detail="Pairing code already used.")
            raise HTTPException(status_code=400, detail="Invalid pairing code.")

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, str | int]:
        _require_protocol(request, allow_missing=True)
        return {
            "status": "ok",
            "version": VERSION,
            "protocol_version": PROTOCOL_VERSION,
        }

    @app.get("/api/worker/status")
    async def worker_status(request: Request) -> dict[str, Any]:
        _require_protocol(request)
        worker = _worker_authorized(request)
        return database_worker_status(worker["id"], database_path=str(data_dir / "localmind.db"))

    @app.post("/api/worker/revoke")
    async def revoke_worker_route(request: Request) -> dict[str, str]:
        _require_protocol(request)
        if not _admin_authorized(request):
            raise HTTPException(status_code=403, detail="Admin access required")
        payload = await request.json()
        worker_id = payload.get("worker_id") if isinstance(payload, dict) else None
        if not worker_id:
            raise HTTPException(status_code=400, detail="worker_id is required")
        revoked = revoke_worker(str(worker_id), database_path=str(data_dir / "localmind.db"))
        if not revoked:
            raise HTTPException(status_code=404, detail="Worker not found")
        return {"status": "revoked", "worker_id": str(worker_id)}

    @app.post("/api/worker/heartbeat")
    async def worker_heartbeat(request: Request, payload: HeartbeatRequest) -> dict[str, Any]:
        _require_protocol(request)
        worker = _worker_authorized(request)
        heartbeat_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with database_connection(data_dir / "localmind.db") as conn:
            conn.execute(
                """
                UPDATE workers
                SET last_seen = ?,
                    cpu_percent = ?,
                    ram_total_mb = ?,
                    ram_available_mb = ?,
                    battery_percent = ?,
                    battery_charging = ?,
                    software_version = ?,
                    protocol_version = ?,
                    status = 'online',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    heartbeat_time,
                    payload.cpu_percent,
                    payload.ram_total_mb,
                    payload.ram_available_mb,
                    payload.battery_percent,
                    int(bool(payload.battery_charging)) if payload.battery_charging is not None else None,
                    payload.software_version,
                    PROTOCOL_VERSION,
                    heartbeat_time,
                    worker["id"],
                ),
            )
        return {
            "status": "ok",
            "worker_id": worker["id"],
            "online": True,
            "last_seen": heartbeat_time,
            "protocol_version": PROTOCOL_VERSION,
        }

    @app.post("/api/worker/claim")
    async def worker_claim(request: Request, payload: ClaimRequest) -> dict[str, Any]:
        _require_protocol(request)
        worker = _worker_authorized(request)
        recover_expired_leases(str(data_dir / "localmind.db"))
        lease_seconds = payload.lease_seconds or 60
        task = claim_task(str(data_dir / "localmind.db"), worker_id=worker["id"], lease_seconds=lease_seconds)
        if task is None:
            return {"task": None, "protocol_version": PROTOCOL_VERSION}
        return {
            "task": {
                "id": task["id"],
                "job_id": task["job_id"],
                "type": task["type"],
                "payload": task["payload"],
                "attempts": task["attempts"],
                "lease_expires_at": task["lease_expires_at"],
                "lease_seconds": task["lease_seconds"],
            },
            "protocol_version": PROTOCOL_VERSION,
        }

    @app.post("/api/worker/tasks/{task_id}/extend")
    async def extend_task(request: Request, task_id: str, payload: ClaimRequest) -> dict[str, Any]:
        _require_protocol(request)
        worker = _worker_authorized(request)
        lease_seconds = payload.lease_seconds or 60
        try:
            result = extend_task_lease(str(data_dir / "localmind.db"), task_id=task_id, worker_id=worker["id"], lease_seconds=lease_seconds)
        except ValueError as exc:
            if str(exc) == "task_not_found":
                raise HTTPException(status_code=404, detail="Task not found")
            if str(exc) == "wrong_worker":
                raise HTTPException(status_code=403, detail="Task leased to another worker")
            if str(exc) == "task_not_leased":
                raise HTTPException(status_code=409, detail="Task is not currently leased")
            raise HTTPException(status_code=400, detail="Invalid lease update")
        return {"status": "ok", **result, "protocol_version": PROTOCOL_VERSION}

    @app.post("/api/worker/tasks/{task_id}/complete")
    async def complete_task_route(request: Request, task_id: str, payload: CompleteTaskRequest) -> dict[str, Any]:
        _require_protocol(request)
        worker = _worker_authorized(request)
        try:
            result = complete_task(str(data_dir / "localmind.db"), task_id=task_id, worker_id=worker["id"], result=payload.result)
        except ValueError as exc:
            if str(exc) == "task_not_found":
                raise HTTPException(status_code=404, detail="Task not found")
            if str(exc) == "wrong_worker":
                raise HTTPException(status_code=403, detail="Task leased to another worker")
            if str(exc) == "lease_expired":
                raise HTTPException(status_code=409, detail="Lease expired")
            if str(exc) == "task_not_leased":
                raise HTTPException(status_code=409, detail="Task is not leased")
            raise HTTPException(status_code=400, detail="Invalid completion")
        return {"status": "ok", **result, "protocol_version": PROTOCOL_VERSION}

    @app.post("/api/worker/tasks/{task_id}/fail")
    async def fail_task_route(request: Request, task_id: str, payload: FailTaskRequest) -> dict[str, Any]:
        _require_protocol(request)
        worker = _worker_authorized(request)
        try:
            result = fail_task(str(data_dir / "localmind.db"), task_id=task_id, worker_id=worker["id"], error=payload.error)
        except ValueError as exc:
            if str(exc) == "task_not_found":
                raise HTTPException(status_code=404, detail="Task not found")
            if str(exc) == "wrong_worker":
                raise HTTPException(status_code=403, detail="Task leased to another worker")
            if str(exc) == "task_not_leased":
                raise HTTPException(status_code=409, detail="Task is not leased")
            raise HTTPException(status_code=400, detail="Invalid failure")
        return {"status": "ok", **result, "protocol_version": PROTOCOL_VERSION}

    @app.get("/datasets")
    async def dataset_page(request: Request) -> HTMLResponse:
        if not _authenticated_user(request):
            return RedirectResponse("/login", status_code=303)
        datasets = list_datasets(data_dir)
        return render_template(
            "datasets.html",
            request=request,
            csrf_token=app.state.csrf_token,
            datasets=datasets,
            max_upload_size_bytes=config.max_dataset_size_bytes,
            upload_success=request.query_params.get("uploaded") == "1",
        )

    async def _register_uploaded_dataset(file: UploadFile) -> dict[str, Any]:
        safe_name = file.filename or "upload.csv"
        if "/" in safe_name or "\\" in safe_name:
            raise HTTPException(status_code=400, detail="Invalid file name")
        raw = await file.read()
        try:
            return register_dataset(
                data_dir,
                filename=safe_name,
                file_bytes=raw,
                max_upload_size_bytes=config.max_dataset_size_bytes,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/datasets/upload")
    async def upload_dataset_from_ui(
        request: Request,
        file: Annotated[UploadFile, File(...)],
        csrf_token: Annotated[str, Form(...)],
    ) -> RedirectResponse:
        if not _authenticated_user(request):
            raise HTTPException(status_code=403, detail="Admin access required")
        if not _validate_csrf({"csrf_token": csrf_token}):
            raise HTTPException(status_code=403, detail="Invalid form token")
        await _register_uploaded_dataset(file)
        return RedirectResponse("/datasets?uploaded=1", status_code=303)

    @app.post("/api/datasets")
    async def upload_dataset(request: Request, file: Annotated[UploadFile, File(...)]) -> dict[str, Any]:
        _require_protocol(request)
        if not _admin_authorized(request):
            raise HTTPException(status_code=403, detail="Admin access required")
        if file is None:
            raise HTTPException(status_code=400, detail="A dataset file is required")
        dataset = await _register_uploaded_dataset(file)
        return {"status": "created", "dataset": dataset, "protocol_version": PROTOCOL_VERSION}

    @app.get("/api/datasets")
    async def list_datasets_route(request: Request) -> dict[str, Any]:
        _require_protocol(request)
        if not _admin_authorized(request):
            raise HTTPException(status_code=403, detail="Admin access required")
        return {"datasets": list_datasets(data_dir), "protocol_version": PROTOCOL_VERSION}

    @app.get("/api/datasets/{dataset_id}")
    async def get_dataset_route(request: Request, dataset_id: str) -> dict[str, Any]:
        _require_protocol(request)
        if not _admin_authorized(request):
            raise HTTPException(status_code=403, detail="Admin access required")
        dataset = get_dataset(data_dir, dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return {"dataset": dataset, "protocol_version": PROTOCOL_VERSION}

    @app.delete("/api/datasets/{dataset_id}")
    async def delete_dataset_route(request: Request, dataset_id: str) -> dict[str, Any]:
        _require_protocol(request)
        if not _admin_authorized(request):
            raise HTTPException(status_code=403, detail="Admin access required")
        try:
            deleted = delete_dataset(data_dir, dataset_id)
        except ValueError as exc:
            if str(exc) == "dataset_in_use":
                raise HTTPException(status_code=409, detail="Dataset is in use by an active job") from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return {"status": "deleted", "dataset_id": dataset_id, "protocol_version": PROTOCOL_VERSION}

    @app.post("/api/jobs")
    async def create_job_route(request: Request, payload: CreateJobRequest) -> dict[str, Any]:
        _require_protocol(request)
        if not _admin_authorized(request):
            raise HTTPException(status_code=403, detail="Admin access required")
        if payload.dataset_id:
            dataset = get_dataset(data_dir, payload.dataset_id)
            if dataset is None:
                raise HTTPException(status_code=404, detail="Dataset not found")
            if dataset.get("validation_status") != "valid":
                raise HTTPException(status_code=400, detail="Dataset is not valid for job linking")
            try:
                ensure_dataset_valid(data_dir, payload.dataset_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        tasks = payload.tasks
        if tasks is None:
            tasks = [{"type": payload.task_type, "payload": {"duration": payload.duration_seconds}, "max_attempts": 3} for _ in range(payload.task_count)]

        normalized_tasks: list[dict[str, Any]] = []
        for task in tasks:
            if isinstance(task, JobTaskSpec):
                normalized_tasks.append({"type": task.type, "payload": task.payload, "max_attempts": task.max_attempts})
            elif isinstance(task, dict):
                normalized_tasks.append({
                    "type": str(task.get("type") or payload.task_type),
                    "payload": task.get("payload") or {"duration": payload.duration_seconds},
                    "max_attempts": int(task.get("max_attempts") or 3),
                })
            else:
                normalized_tasks.append({"type": payload.task_type, "payload": {"duration": payload.duration_seconds}, "max_attempts": 3})

        if len(normalized_tasks) > 1:
            job = create_job(
                str(data_dir / "localmind.db"),
                name=payload.name,
                tasks=normalized_tasks,
                dataset_id=payload.dataset_id,
            )
        else:
            first = normalized_tasks[0] if normalized_tasks else {"type": payload.task_type, "payload": {"duration": payload.duration_seconds}, "max_attempts": 3}
            job = create_demo_job(
                str(data_dir / "localmind.db"),
                name=payload.name,
                task_count=1,
                task_type=str(first.get("type") or payload.task_type),
                duration_seconds=float(first.get("payload", {}).get("duration", payload.duration_seconds)),
            )
            if payload.dataset_id:
                with database_connection(data_dir / "localmind.db") as conn:
                    conn.execute("UPDATE jobs SET dataset_id = ? WHERE id = ?", (payload.dataset_id, job["id"]))
                    conn.commit()
        return {"status": "created", "job": job, "protocol_version": PROTOCOL_VERSION}

    @app.get("/api/jobs/{job_id}")
    async def get_job_route(request: Request, job_id: str) -> dict[str, Any]:
        _require_protocol(request)
        if not _admin_authorized(request):
            raise HTTPException(status_code=403, detail="Admin access required")
        try:
            return get_job_progress(str(data_dir / "localmind.db"), job_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Job not found")

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job_route(request: Request, job_id: str) -> dict[str, Any]:
        _require_protocol(request)
        if not _admin_authorized(request):
            raise HTTPException(status_code=403, detail="Admin access required")
        try:
            return cancel_job(str(data_dir / "localmind.db"), job_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Job not found")

    return app
