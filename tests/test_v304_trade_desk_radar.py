from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.instruments import get_instrument, instrument_registry
from backend.services.market_data import market_data_service
from backend.services.setup_service import build_candidate_setup

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT.joinpath("frontend/index.html").read_text(encoding="utf-8")
CSS = ROOT.joinpath("frontend/styles.css").read_text(encoding="utf-8")
APP = ROOT.joinpath("frontend/app.js").read_text(encoding="utf-8")
MAIN = ROOT.joinpath("backend/main.py").read_text(encoding="utf-8")
MARKET_DATA = ROOT.joinpath("backend/services/market_data.py").read_text(encoding="utf-8")
RADAR = ROOT.joinpath("backend/services/multi_market_monitor.py").read_text(encoding="utf-8")
ENV = ROOT.joinpath(".env.example").read_text(encoding="utf-8")


def test_v304_trade_desk_interface_contract():
    for marker in [
        'id="deskRailToggle"',
        'data-desk-tab="setup"',
        'data-desk-tab="claude"',
        'data-desk-tab="radar"',
        'id="marketRadarPanel"',
        'id="marketRadarList"',
        'id="enableMarketNotifications"',
        'data-tf="2"',
    ]:
        assert marker in HTML
    assert ".tv-chart-rail .desk-pane.active" in CSS
    assert ".tv-chart-layout.desk-collapsed" in CSS
    assert "processMarketOpportunities" in APP
    assert "restoreCachedMarket" in APP
    assert "3.0.4-trade-desk-market-radar" in MAIN
    assert ">Overview</button>" in HTML
    assert ">Trade Desk</button>" in HTML
    assert "_load_history_since" in MARKET_DATA
    assert 'status = "SETUP_FORMING" if qualified else "STALE_DATA"' in RADAR
    assert "MULTI_MARKET_MAX_DATA_AGE_SECONDS=180" in ENV


def test_background_candidate_can_use_es_without_switching_active_market():
    active_before = instrument_registry.active.symbol
    candles = market_data_service.cached_snapshot("ES")
    setup = build_candidate_setup(candles, get_instrument("ES"), None)
    assert setup.symbol == "ES"
    assert setup.primary_entry_model
    assert instrument_registry.active.symbol == active_before


def test_multi_market_api_and_coherent_switch_response():
    with TestClient(app) as client:
        radar = client.get("/api/multi-market/opportunities")
        assert radar.status_code == 200
        payload = radar.json()
        assert "items" in payload
        assert payload["status"]["symbols"] == ["NQ", "ES", "GC"]

        active = client.get("/api/instruments").json()["active_symbol"]
        switched = client.post("/api/market/symbol", json={"symbol": active})
        assert switched.status_code == 200
        body = switched.json()
        assert body["symbol"] == active
        assert body["setup"]["symbol"] == active
