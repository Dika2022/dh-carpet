from fastapi.testclient import TestClient

from app.api.dependencies import get_health_service
from app.main import create_app


class StubHealthService:
    def __init__(self, services: dict[str, str]) -> None:
        self._services = services

    async def check(self) -> dict[str, str]:
        return self._services


def test_health_endpoint_reports_available_services() -> None:
    application = create_app()
    application.dependency_overrides[get_health_service] = lambda: StubHealthService(
        {"postgres": "ok", "redis": "ok", "qdrant": "ok"}
    )

    with TestClient(application, raise_server_exceptions=True) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {
            "postgres": "ok",
            "redis": "ok",
            "qdrant": "ok",
        },
    }


def test_health_endpoint_reports_degraded_state() -> None:
    application = create_app()
    application.dependency_overrides[get_health_service] = lambda: StubHealthService(
        {"postgres": "ok", "redis": "error", "qdrant": "ok"}
    )

    with TestClient(application, raise_server_exceptions=True) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["services"]["redis"] == "error"

