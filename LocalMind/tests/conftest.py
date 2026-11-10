import pytest
from fastapi.testclient import TestClient

from localmind.admin.app import create_app
from localmind.admin.config import AdminConfig


@pytest.fixture
def temp_data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def admin_config(temp_data_dir):
    temp_data_dir.mkdir(exist_ok=True)
    return AdminConfig(
        host="127.0.0.1",
        port=8001,
        data_dir=str(temp_data_dir),
        lease_seconds=60,
        max_attempts=3,
    )


@pytest.fixture
def client(admin_config):
    app = create_app(admin_config)
    with TestClient(app) as c:
        yield c
