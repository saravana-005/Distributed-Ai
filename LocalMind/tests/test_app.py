from fastapi.testclient import TestClient

from localmind.admin.app import create_app


def test_health_endpoint(admin_config):
    app = create_app(admin_config)
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["version"]
        assert payload["protocol_version"] == 1
        assert "password" not in payload


def test_root_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code in (200, 302, 303)
    if response.status_code in (302, 303):
        assert response.headers["Location"].endswith("/login")


def test_login_form_available(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"LocalMind Admin" in response.content


def test_login_failure(client):
    response = client.post("/login", data={"password": "wrong"}, follow_redirects=False)
    assert response.status_code in (200, 401)


def test_successful_login_and_logout(client):
    password = client.app.state.admin_password
    response = client.post(
        "/login",
        data={"password": password, "csrf_token": client.app.state.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code in (200, 302, 303)
    response = client.post(
        "/logout",
        data={"csrf_token": client.app.state.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code in (200, 302, 303)


def test_dashboard_access_control(client):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code in (302, 303, 401)
