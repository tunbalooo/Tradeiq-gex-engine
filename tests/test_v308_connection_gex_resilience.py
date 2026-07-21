from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.api import routes as routes_module

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT.joinpath("frontend/app.js").read_text(encoding="utf-8")
MAIN = ROOT.joinpath("backend/main.py").read_text(encoding="utf-8")
SW = ROOT.joinpath("frontend/service-worker.js").read_text(encoding="utf-8")
ROUTES = ROOT.joinpath("backend/api/routes.py").read_text(encoding="utf-8")


def test_v308_frontend_transport_and_gex_contract():
    assert "3.0.8-connection-gex-resilience" in MAIN
    assert 'const CACHE_NAME = "tradeiq-v3.0.8-connection-gex-resilience-shell"' in SW
    assert "WebSocket handshake timed out; enabling REST fallback" in APP_JS
    assert "startRestFallback" in APP_JS
    assert "pollRestFallback" in APP_JS
    assert 'fetch("/api/live-state"' in APP_JS
    assert "SERVER REST FALLBACK" in APP_JS
    assert "state.setup?.gex || state.gexSummary" in APP_JS
    assert '@router.get("/live-state")' in ROUTES


def test_live_state_supplies_chart_setup_and_independent_gex():
    with TestClient(app) as client:
        response = client.get("/api/live-state")
        assert response.status_code == 200
        payload = response.json()

    assert payload["type"] == "market_update"
    assert payload["transport"] == "rest"
    assert payload["market"]["candle_count"] > 0
    assert payload["candle"] is not None
    assert payload["gex_summary"] is not None
    assert payload["gex_summary"]["applied_to_symbol"] == payload["market"]["symbol"]


def test_gex_summary_remains_available_while_setup_engine_is_warming(monkeypatch):
    monkeypatch.setattr(routes_module.trade_engine_service, "current_setup", lambda: None)
    with TestClient(app) as client:
        response = client.get("/api/gex/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["gamma_flip"] > 0
    assert payload["call_wall"] > payload["put_wall"]


def test_websocket_payload_carries_gex_even_without_setup_dependency():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/market") as websocket:
            payload = websocket.receive_json()

    assert payload["type"] == "market_update"
    assert payload["gex_summary"] is not None
    assert payload["gex_summary"]["gamma_flip"] > 0


def test_previous_databento_session_is_force_terminated_before_replacement(monkeypatch):
    from backend.services.market_data import DatabentoMarketDataService
    from backend.services import market_data as market_data_module

    service = DatabentoMarketDataService()

    class FakeThread:
        alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            return None

    thread = FakeThread()

    class FakeClient:
        stopped = False
        terminated = False

        def stop(self):
            self.stopped = True

        def terminate(self):
            self.terminated = True
            thread.alive = False

    client = FakeClient()
    service._thread = thread
    service._live_client = client
    monkeypatch.setattr(market_data_module.settings, "databento_stop_join_seconds", 0.5)

    service._stop_live_client(wait=True)

    assert client.stopped is True
    assert client.terminated is True
    assert service._thread is None
    assert service._live_client is None
