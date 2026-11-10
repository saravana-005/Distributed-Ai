from __future__ import annotations

from fastapi.testclient import TestClient

from localmind.admin.app import create_app


def _login(client):
    admin_password = client.app.state.admin_password
    response = client.post(
        "/login",
        data={"password": admin_password, "csrf_token": client.app.state.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code in (200, 302, 303)
    return admin_password


def test_dataset_upload_and_listing(admin_config):
    app = create_app(admin_config)
    with TestClient(app) as client:
        admin_password = _login(client)
        csv_data = b"feature,value\n1,10\n2,20\n"
        response = client.post(
            "/api/datasets",
            files={"file": ("sample.csv", csv_data, "text/csv")},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["dataset"]["name"] == "sample.csv"
        data = client.get(
            "/api/datasets",
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert data.status_code == 200
        datasets = data.json()["datasets"]
        assert len(datasets) >= 1


def test_dataset_upload_from_admin_ui_uses_session_and_csrf(admin_config):
    app = create_app(admin_config)
    with TestClient(app) as client:
        _login(client)
        response = client.post(
            "/datasets/upload",
            data={"csrf_token": client.app.state.csrf_token},
            files={"file": ("from-ui.csv", b"feature,value\n1,10\n", "text/csv")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/datasets?uploaded=1"
        page = client.get(response.headers["location"])
        assert page.status_code == 200
        assert "Dataset uploaded successfully." in page.text
        assert "from-ui.csv" in page.text


def test_dataset_rejects_empty_and_malformed_files(admin_config):
    app = create_app(admin_config)
    with TestClient(app) as client:
        admin_password = _login(client)

        empty = client.post(
            "/api/datasets",
            files={"file": ("empty.csv", b"", "text/csv")},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert empty.status_code == 400

        malformed = client.post(
            "/api/datasets",
            files={"file": ("bad.csv", b"feature,value\n1,2\n3,4,5\n", "text/csv")},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert malformed.status_code == 400


def test_dataset_rejects_unsupported_and_malicious_names(admin_config):
    app = create_app(admin_config)
    with TestClient(app) as client:
        admin_password = _login(client)

        bad_ext = client.post(
            "/api/datasets",
            files={"file": ("file.txt", b"a,b\n1,2\n", "text/plain")},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert bad_ext.status_code == 400

        malicious = client.post(
            "/api/datasets",
            files={"file": ("../../escape.csv", b"x,y\n1,2\n", "text/csv")},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert malicious.status_code == 400


def test_dataset_job_linking_and_delete_guard(admin_config):
    app = create_app(admin_config)
    with TestClient(app) as client:
        admin_password = _login(client)
        upload = client.post(
            "/api/datasets",
            files={"file": ("training.csv", b"feature,label\n1,ok\n2,ok\n", "text/csv")},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert upload.status_code == 200
        dataset_id = upload.json()["dataset"]["id"]

        job_response = client.post(
            "/api/jobs",
            json={"name": "with-dataset", "dataset_id": dataset_id, "task_count": 1, "task_type": "noop", "duration_seconds": 0.1},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert job_response.status_code == 200

        delete_result = client.delete(
            f"/api/datasets/{dataset_id}",
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert delete_result.status_code == 409


def test_dataset_has_sha256_and_storage_metadata(admin_config):
    app = create_app(admin_config)
    with TestClient(app) as client:
        admin_password = _login(client)
        csv_data = b"one,two\n3,4\n5,6\n"
        upload = client.post(
            "/api/datasets",
            files={"file": ("meta.csv", csv_data, "text/csv")},
            headers={"X-LocalMind-Protocol": "1", "Authorization": f"Bearer {admin_password}"},
        )
        assert upload.status_code == 200
        dataset = upload.json()["dataset"]
        assert dataset["sha256"]
        assert dataset["size_bytes"] == len(csv_data)
        assert dataset["rows"] == 2
