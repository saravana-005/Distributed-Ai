from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from localmind.admin.queue import recover_expired_leases


def test_phase3_claim_and_complete_flow(admin_config):
    from localmind.admin.app import create_app

    app = create_app(admin_config)
    with TestClient(app) as client:
        admin_password = client.app.state.admin_password
        login = client.post(
            "/login",
            data={"password": admin_password, "csrf_token": client.app.state.csrf_token},
            follow_redirects=False,
        )
        assert login.status_code in (200, 302, 303)

        pair = client.post("/dashboard/pair", data={"csrf_token": client.app.state.csrf_token}, follow_redirects=False)
        assert pair.status_code in (200, 302, 303)
        code = client.app.state.generated_pairing_code
        assert code

        pair_response = client.post(
            "/api/pair",
            json={"code": code, "worker_name": "phase3-worker"},
            headers={"X-LocalMind-Protocol": "1"},
        )
        assert pair_response.status_code == 200
        worker_token = pair_response.json()["worker_token"]

        job_response = client.post(
            "/api/jobs",
            json={"name": "demo", "task_count": 2, "task_type": "noop", "duration_seconds": 0.1},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert job_response.status_code == 200
        job_id = job_response.json()["job"]["id"]

        claim = client.post(
            "/api/worker/claim",
            json={"lease_seconds": 60},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {worker_token}"},
        )
        assert claim.status_code == 200
        task = claim.json()["task"]
        assert task is not None

        complete = client.post(
            f"/api/worker/tasks/{task['id']}/complete",
            json={"result": {"status": "ok"}},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {worker_token}"},
        )
        assert complete.status_code == 200

        status = client.get(
            f"/api/jobs/{job_id}",
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert status.status_code == 200
        payload = status.json()
        assert payload["completed"] >= 1


def test_phase3_expired_lease_recovery(admin_config):
    from localmind.admin.app import create_app

    app = create_app(admin_config)
    with TestClient(app) as client:
        admin_password = client.app.state.admin_password
        login = client.post(
            "/login",
            data={"password": admin_password, "csrf_token": client.app.state.csrf_token},
            follow_redirects=False,
        )
        assert login.status_code in (200, 302, 303)

        pair = client.post("/dashboard/pair", data={"csrf_token": client.app.state.csrf_token}, follow_redirects=False)
        assert pair.status_code in (200, 302, 303)
        code = client.app.state.generated_pairing_code
        assert code

        pair_response = client.post(
            "/api/pair",
            json={"code": code, "worker_name": "lease-worker"},
            headers={"X-LocalMind-Protocol": "1"},
        )
        assert pair_response.status_code == 200
        worker_token = pair_response.json()["worker_token"]

        job_response = client.post(
            "/api/jobs",
            json={"name": "lease-job", "task_count": 1, "task_type": "noop", "duration_seconds": 0.1},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert job_response.status_code == 200

        claim = client.post(
            "/api/worker/claim",
            json={"lease_seconds": 0},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {worker_token}"},
        )
        assert claim.status_code == 200
        task = claim.json()["task"]
        assert task is not None

        db_path = admin_config.database_path
        with __import__("sqlite3").connect(str(db_path)) as conn:
            conn.execute(
                "UPDATE tasks SET lease_expires_at = ?, updated_at = ? WHERE id = ?",
                ((datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), task["id"]),
            )
            conn.commit()

        recovered = recover_expired_leases(str(db_path))
        assert len(recovered) >= 1

        claimed_again = client.post(
            "/api/worker/claim",
            json={"lease_seconds": 60},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {worker_token}"},
        )
        assert claimed_again.status_code == 200
        claimed = claimed_again.json()["task"]
        assert claimed is not None
        assert claimed["id"] == task["id"]
