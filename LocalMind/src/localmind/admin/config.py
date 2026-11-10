from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdminConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOCALMIND_ADMIN_",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    data_dir: str = "./data"
    lease_seconds: int = Field(default=60, gt=0)
    max_attempts: int = Field(default=3, gt=0)
    dataset_max_size_mb: int = Field(default=50, gt=0, le=2048)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        if not value or value.strip() == "":
            raise ValueError("host cannot be empty")
        return value

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def database_path(self) -> Path:
        return self.data_path / "localmind.db"

    @property
    def secret_path(self) -> Path:
        return self.data_path / "admin-secret.key"

    @property
    def admin_file_path(self) -> Path:
        return self.data_path / "admin.json"

    @property
    def max_dataset_size_bytes(self) -> int:
        return self.dataset_max_size_mb * 1024 * 1024
