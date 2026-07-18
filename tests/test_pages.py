from fastapi.testclient import TestClient
from backend.main import app


def test_all_page_endpoints_work():
    with TestClient(app) as client:
        for path in ["/api/health","/api/dashboard","/api/setup/current","/api/gex/summary","/api/confluence","/api/setups/history","/api/alerts","/api/positions","/api/settings"]:
            response=client.get(path)
            assert response.status_code==200, path
        result=client.post("/api/backtest",json={"timeframe":5,"minimum_score":75,"target_r":2,"max_bars":500})
        assert result.status_code==200
        assert "equity_curve" in result.json()
