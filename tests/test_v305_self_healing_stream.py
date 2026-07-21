import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.main import app
from backend.models.schemas import Candle
from backend.services import market_data as market_data_module
from backend.services.databento_gex import gex_service
from backend.services.instruments import get_instrument
from backend.services.market_data import DatabentoMarketDataService

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT.joinpath("backend/main.py").read_text(encoding="utf-8")
MARKET_DATA = ROOT.joinpath("backend/services/market_data.py").read_text(encoding="utf-8")
APP = ROOT.joinpath("frontend/app.js").read_text(encoding="utf-8")
HTML = ROOT.joinpath("frontend/index.html").read_text(encoding="utf-8")
SW = ROOT.joinpath("frontend/service-worker.js").read_text(encoding="utf-8")
ENV = ROOT.joinpath(".env.example").read_text(encoding="utf-8")


def candle(at: datetime, price: float) -> Candle:
    return Candle(
        time=at,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price + 0.25,
        volume=10,
    )


def test_v305_runtime_and_frontend_contract():
    assert "3.0.5-self-healing-market-stream" in MAIN
    assert "_live_watchdog_loop" in MARKET_DATA
    assert "_recover_active_gap" in MARKET_DATA
    assert "reconnect_policy=\"reconnect\"" in MARKET_DATA
    assert "component_errors" in MAIN
    assert "heartbeat" in MAIN
    assert "startSocketWatchdog" in APP
    assert "scheduleWebSocketReconnect" in APP
    assert 'id="dataAgeLabel"' in HTML
    assert "tradeiq-v3.0.5-self-healing-market-stream-shell" in SW
    assert "DATABENTO_LIVE_STALE_SECONDS=45" in ENV



def test_cme_watchdog_respects_daily_maintenance_and_sunday_open():
    assert market_data_module._cme_globex_expected_live(datetime(2026, 7, 21, 20, 30, tzinfo=timezone.utc)) is True
    assert market_data_module._cme_globex_expected_live(datetime(2026, 7, 21, 21, 30, tzinfo=timezone.utc)) is False
    assert market_data_module._cme_globex_expected_live(datetime(2026, 7, 19, 21, 0, tzinfo=timezone.utc)) is False
    assert market_data_module._cme_globex_expected_live(datetime(2026, 7, 19, 22, 0, tzinfo=timezone.utc)) is True

def test_health_marks_a_silent_live_stream_stale(monkeypatch):
    service = DatabentoMarketDataService()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    service._started = True
    service.stream_state = "LIVE"
    service.connected = True
    service.last_record_at = now - timedelta(minutes=4)
    service.last_candle_at = now - timedelta(minutes=4)
    service.candles.append(candle(service.last_candle_at, 29000.0))
    monkeypatch.setattr(market_data_module, "_cme_globex_expected_live", lambda _now=None: True)

    health = service.health()

    assert health["stream_state"] == "STALE"
    assert health["connected"] is False
    assert health["data_fresh"] is False
    assert health["last_record_age_seconds"] >= 239


def test_incremental_gap_recovery_preserves_existing_candles():
    service = DatabentoMarketDataService()
    profile = get_instrument("NQ")
    service.instrument = profile
    service._generation = 7
    base = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)
    service.candles.extend([candle(base, 29000.0), candle(base + timedelta(minutes=1), 29001.0)])
    loaded = [
        candle(base + timedelta(minutes=1), 29001.5),
        candle(base + timedelta(minutes=2), 29002.0),
    ]

    service._merge_active_incremental_history(profile, loaded, 7)
    values = service.snapshot()

    assert [item.time for item in values] == [
        base,
        base + timedelta(minutes=1),
        base + timedelta(minutes=2),
    ]
    assert values[1].open == 29001.5
    assert service.history_source == "databento-recovered"


def test_live_worker_recreates_client_after_unexpected_close(monkeypatch):
    service = DatabentoMarketDataService()
    service._started = True
    service._generation = 3
    profile = get_instrument("NQ")
    stop_event = threading.Event()
    clients = []

    class FakeClient:
        def __init__(self, number: int):
            self.number = number

        def subscribe(self, **_kwargs):
            return None

        def add_callback(self, *_args):
            return None

        def start(self):
            return None

        def block_for_close(self):
            if self.number == 1:
                raise RuntimeError("temporary link failure")
            stop_event.set()

        def stop(self):
            return None

    def live_factory(**_kwargs):
        client = FakeClient(len(clients) + 1)
        clients.append(client)
        return client

    monkeypatch.setattr(service, "_import_db", lambda: SimpleNamespace(Live=live_factory))
    monkeypatch.setattr(market_data_module.settings, "databento_reconnect_initial_seconds", 0.001)
    monkeypatch.setattr(market_data_module.settings, "databento_reconnect_max_seconds", 0.002)

    service._run_live(profile, 3, stop_event)

    assert len(clients) == 2
    assert service.total_reconnects == 1
    assert service.last_disconnect_reason == "temporary link failure"


def test_websocket_component_failure_does_not_close_market_stream(monkeypatch):
    monkeypatch.setattr(gex_service, "health", lambda: (_ for _ in ()).throw(RuntimeError("gex unavailable")))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/market") as websocket:
            payload = websocket.receive_json()

    assert payload["type"] == "market_update"
    assert payload["server"]["status"] == "LIVE"
    assert payload["server"]["heartbeat"] == 1
    assert any(item.startswith("gex:") for item in payload["component_errors"])
    assert payload["market"]
