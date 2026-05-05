from fastapi.testclient import TestClient

from baudoku_api.main import create_app


def test_healthcheck() -> None:
    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
