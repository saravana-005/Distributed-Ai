import json

from localmind.admin.auth import (
    create_session_cookie,
    hash_password,
    initialize_admin_account,
    is_valid_password,
    verify_session_cookie,
)


def test_password_hash_verification():
    password = "super-secret"
    hashed = hash_password(password)
    assert is_valid_password(password, hashed)
    assert not is_valid_password("wrong", hashed)


def test_first_run_credential_initialization(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    password = initialize_admin_account(data_dir)
    assert password

    creds_path = data_dir / "admin.json"
    payload = json.loads(creds_path.read_text())
    assert "password_hash" in payload
    assert "salt" in payload
    assert "password" not in payload
    assert is_valid_password(password, payload["password_hash"])


def test_session_login_logout(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    password = initialize_admin_account(data_dir)
    secret = data_dir / "admin-secret.key"
    token = create_session_cookie(password, secret_path=secret)
    assert token
    assert verify_session_cookie(token, secret_path=secret) == password
