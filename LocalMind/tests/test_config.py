import pytest
from pydantic import ValidationError

from localmind.admin.config import AdminConfig


def test_default_config():
    config = AdminConfig()
    assert config.host == "0.0.0.0"
    assert config.port == 8000
    assert config.data_dir == "./data"
    assert config.lease_seconds == 60
    assert config.max_attempts == 3


def test_valid_overrides():
    config = AdminConfig(
        host="127.0.0.1",
        port=9000,
        data_dir="./tmp-data",
        lease_seconds=120,
        max_attempts=5,
    )
    assert config.host == "127.0.0.1"
    assert config.port == 9000
    assert config.data_dir == "./tmp-data"
    assert config.lease_seconds == 120
    assert config.max_attempts == 5


def test_invalid_port():
    with pytest.raises(ValidationError):
        AdminConfig(port=70000)


def test_invalid_max_attempts():
    with pytest.raises(ValidationError):
        AdminConfig(max_attempts=0)
