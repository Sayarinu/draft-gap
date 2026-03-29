from __future__ import annotations


def test_health_endpoint_is_public(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": "1.0.0"}
