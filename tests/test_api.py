from fastapi.testclient import TestClient

from backend.main import app


def test_dashboard_and_setup_endpoints():
    with TestClient(app) as client:
        health = client.get("/api/health")
        dashboard = client.get("/api/dashboard")
        market = client.get("/api/market/snapshot?timeframe=5&limit=500")

    assert health.status_code == 200
    assert health.json()["mode"] == "simulated"
    assert dashboard.status_code == 200
    assert dashboard.json()["setup"]["gex"]["call_wall"] > 0
    assert dashboard.json()["meta"]["overview"]
    assert market.status_code == 200
    assert len(market.json()["candles"]) > 20
