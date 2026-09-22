from __future__ import annotations

from fastapi.testclient import TestClient

from reactor_backend.config import Settings
from reactor_backend.main import create_app


class FakeDatabase:
    def __init__(self, _settings: Settings, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def ping(self) -> None:
        if not self.healthy:
            raise ConnectionError("database unavailable")

    async def close(self) -> None:
        self.closed = True


def test_liveness_has_no_dependency_check_and_request_id() -> None:
    app = create_app(Settings(), lambda settings: FakeDatabase(settings, healthy=False))
    with TestClient(app) as client:
        response = client.get("/internal/health/live", headers={"X-Request-ID": "test-123"})

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "service": "reactor-backend-python"}
    assert response.headers["X-Request-ID"] == "test-123"


def test_readiness_is_up_when_mysql_ping_succeeds() -> None:
    app = create_app(Settings(), FakeDatabase)
    with TestClient(app) as client:
        response = client.get("/internal/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "checks": {"mysql": "UP"}}


def test_readiness_is_down_when_mysql_ping_fails() -> None:
    app = create_app(Settings(), lambda settings: FakeDatabase(settings, healthy=False))
    with TestClient(app) as client:
        response = client.get("/internal/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "DOWN", "checks": {"mysql": "DOWN"}}


def test_unsafe_request_id_is_replaced() -> None:
    app = create_app(Settings(), FakeDatabase)
    with TestClient(app) as client:
        response = client.get("/internal/health/live", headers={"X-Request-ID": "bad value\n"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad value\n"
