import pytest
from fastapi.testclient import TestClient

from localmind.admin.app import create_app
from localmind.admin.config import AdminConfig
from localmind.admin.pairing import generate_pairing_code, hash_pairing_code


@pytest.fixture
def phase2_config(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return AdminConfig(host="127.0.0.1", port=8002, data_dir=str(data_dir))


def test_pairing_code_has_expected_format():
    code = generate_pairing_code()
    assert len(code) == 10
    assert code[4] == "-"
    assert code.replace("-", "").isalnum()
    assert hash_pairing_code(code)


def test_pairing_and_heartbeat_workflow(phase2_config):
    app = create_app(phase2_config)
    with TestClient(app) as client:
        # generate code through admin dashboard action
        login = client.post(
            "/login",
            data={
                "password": client.app.state.admin_password,
                "csrf_token": client.app.state.csrf_token,
            },
            follow_redirects=False,
        )
        assert login.status_code in (200, 302, 303)

        pair_response = client.post(
            "/dashboard/pair",
            data={"csrf_token": client.app.state.csrf_token},
            follow_redirects=False,
        )
        assert pair_response.status_code in (200, 302, 303)

        code = client.app.state.generated_pairing_code
        assert code
        assert code.count("-") == 1

        pair_api = client.post(
            "/api/pair",
            json={"code": code, "worker_name": "test-worker"},
            headers={"X-LocalMind-Protocol": "1"},
        )
        assert pair_api.status_code == 200, pair_api.text
        payload = pair_api.json()
        worker_id = payload["worker_id"]
        token = payload["worker_token"]
        assert worker_id
        assert token

        heartbeat = client.post(
            "/api/worker/heartbeat",
            json={
                "cpu_percent": 23.5,
                "ram_total_mb": 4096,
                "ram_available_mb": 3200,
                "battery_percent": 77,
                "battery_charging": False,
                "software_version": "1.2.3",
            },
            headers={
                "X-LocalMind-Protocol": "1",
                "Authorization": f"Bearer {token}",
            },
        )
        assert heartbeat.status_code == 200, heartbeat.text

        revoked = client.post(
            "/api/worker/revoke",
            json={"worker_id": worker_id},
            headers={
                "X-LocalMind-Protocol": "1",
                "Authorization": f"Bearer {client.app.state.admin_password}",
            },
        )
        assert revoked.status_code in (200, 204, 403)


def test_invalid_protocol_version_rejected(phase2_config):
    app = create_app(phase2_config)
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"X-LocalMind-Protocol": "999"})
        assert response.status_code == 426
