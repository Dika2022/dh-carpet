from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

REQUIRED_ENVIRONMENT = {
    "APP_ENV": "test",
    "SERVICE_CHECK_TIMEOUT_SECONDS": "1",
    "POSTGRES_HOST": "postgres",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "dhcarpet",
    "POSTGRES_USER": "dhapp",
    "POSTGRES_PASSWORD": "test-placeholder",
    "REDIS_HOST": "redis",
    "REDIS_PORT": "6379",
    "QDRANT_HOST": "qdrant",
    "QDRANT_PORT": "6333",
}


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.postgres_db == "dhcarpet"
    assert settings.postgres_user == "dhapp"
    assert settings.database_url.drivername == "postgresql+psycopg"
    assert settings.database_url.password == "test-placeholder"
    assert settings.redis_host == "redis"
    assert settings.qdrant_port == 6333


def test_postgres_password_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("POSTGRES_PASSWORD")
    monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_postgres_password_is_loaded_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in REQUIRED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    secret_file = tmp_path / "postgres_password"
    secret_file.write_text("file-placeholder\n", encoding="utf-8")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(secret_file))

    settings = Settings()  # type: ignore[call-arg]

    assert settings.database_url.password == "file-placeholder"
    assert "file-placeholder" not in repr(settings)
