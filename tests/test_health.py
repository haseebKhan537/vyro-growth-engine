from fastapi.testclient import TestClient

from vyro_growth.main import app


def test_health_defaults_outbound_off() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["outbound_enabled"] is False
    assert body["live_providers_enabled"] is False
