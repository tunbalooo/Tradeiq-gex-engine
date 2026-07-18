from fastapi.testclient import TestClient

from backend.main import app
from backend.services.instruments import get_instrument


def test_instrument_profiles_cover_requested_markets():
    expectations = {
        "NQ": ("NQ.v.0", "NQ.OPT", "NQ", 0.25),
        "MNQ": ("MNQ.v.0", "NQ.OPT", "NQ", 0.25),
        "ES": ("ES.v.0", "ES.OPT", "ES", 0.25),
        "MES": ("MES.v.0", "ES.OPT", "ES", 0.25),
        "GC": ("GC.v.0", "OG.OPT", "GC", 0.10),
        "MGC": ("MGC.v.0", "OG.OPT", "GC", 0.10),
    }
    for symbol, expected in expectations.items():
        profile = get_instrument(symbol)
        assert (profile.futures_continuous, profile.options_parent, profile.gex_source_symbol, profile.tick_size) == expected


def test_symbol_selector_switches_engine_and_parent_gex_mapping():
    with TestClient(app) as client:
        instruments = client.get("/api/instruments")
        assert instruments.status_code == 200
        assert {item["symbol"] for item in instruments.json()["items"]} == {"NQ", "MNQ", "ES", "MES", "GC", "MGC"}

        es = client.post("/api/market/symbol", json={"symbol": "ES"})
        assert es.status_code == 200
        assert es.json()["setup"]["symbol"] == "ES"
        assert es.json()["instrument"]["futures_continuous"] == "ES.v.0"
        assert es.json()["setup"]["gex"]["source_symbol"] == "ES"

        mgc = client.post("/api/market/symbol", json={"symbol": "MGC"})
        assert mgc.status_code == 200
        payload = mgc.json()
        assert payload["setup"]["symbol"] == "MGC"
        assert payload["setup"]["gex"]["source_symbol"] == "GC"
        assert payload["setup"]["gex"]["applied_to_symbol"] == "MGC"
        assert payload["setup"]["gex"]["is_parent_market"] is True
        assert payload["instrument"]["tick_size"] == 0.10

        # Leave the shared single-user development server in its default state.
        restored = client.post("/api/market/symbol", json={"symbol": "NQ"})
        assert restored.status_code == 200


def test_invalid_market_symbol_is_rejected():
    with TestClient(app) as client:
        response = client.post("/api/market/symbol", json={"symbol": "BTC"})
    assert response.status_code == 400
