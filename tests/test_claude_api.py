from fastapi.testclient import TestClient

from backend.main import app


def test_claude_status_endpoint_is_safe_when_disabled():
    with TestClient(app) as client:
        response = client.get("/api/ai/status")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["model"]
    assert "configured" in data
    assert "last_error" in data


def test_claude_stream_reports_disabled_without_external_call():
    with TestClient(app) as client:
        response = client.get("/api/ai/analysis/stream")
    assert response.status_code == 200
    assert "event: analysis_error" in response.text
    assert "Claude analysis is disabled" in response.text
