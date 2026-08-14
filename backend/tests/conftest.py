from collections.abc import Iterator

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def application_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
    values = {
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
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
