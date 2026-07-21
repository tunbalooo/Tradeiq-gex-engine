from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.models.schemas import Candle
from backend.services.setup_service import build_candidate_setup
from backend.services.trade_engine import TradeEngineService

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _candidate(**updates):
    setup = build_candidate_setup()
    base = {
        "direction": "LONG", "confidence": 62.0, "entry_valid": True, "actionable": False,
        "entry": 100.0, "stop_loss": 95.0, "take_profit_1": 105.0,
        "take_profit_2": 110.0, "risk_reward": 2.0, "status": "DEVELOPING",
        "order_state": "PREVIEW_ONLY",
    }
    base.update(updates)
    return setup.model_copy(update=base)


def _candle(at, low=99.0, high=101.0):
    return Candle(time=at, open=100, high=high, low=low, close=100, volume=1)


def test_monitoring_trigger_is_not_an_executable_entry(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    now = datetime(2026, 7, 20, 2, 0, tzinfo=timezone.utc)
    watching = service._start_watching(_candidate(), _candle(now))
    assert watching.order_state == "WATCHING"
    assert watching.watch_trigger == 100.0
    assert watching.entry is None
    assert watching.stop_loss is None
    assert watching.take_profit_1 is None
    assert watching.take_profit_2 is None


def test_early_trigger_touch_starts_confirmation_window_without_a_fill(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    start = datetime(2026, 7, 20, 2, 0, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])
    watching = service._start_watching(_candidate(), _candle(start, low=101, high=102))
    clock["now"] = start + timedelta(minutes=5)
    touched = service._advance_watching(watching, _candidate(), _candle(clock["now"], low=99, high=101))
    assert touched.order_state == "WATCHING"
    assert touched.watch_phase == "TRIGGER_TOUCHED"
    assert touched.watch_touch_at == clock["now"]
    assert touched.filled_at is None
    assert touched.entry is None


def test_confirmed_limit_then_touch_fills_and_keeps_plan(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    start = datetime(2026, 7, 20, 2, 0, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])
    watching = service._start_watching(_candidate(), _candle(start, low=101, high=102))
    clock["now"] = start + timedelta(minutes=5)
    armed = service._advance_watching(watching, _candidate(actionable=True), _candle(clock["now"], low=101, high=102))
    assert armed.order_state == "WAITING_FOR_LIMIT"
    assert armed.entry == 100.0 and armed.stop_loss == 95.0
    clock["now"] += timedelta(minutes=5)
    filled = service._advance(armed, _candidate(actionable=True), _candle(clock["now"], low=99, high=101))
    assert filled.order_state == "FILLED"
    assert filled.take_profit_1 == 105.0 and filled.take_profit_2 == 110.0


def test_mobile_uses_official_lightweight_charts_and_clear_labels():
    assert "if (!LC)" in CHART
    assert "if (!LC || USE_MOBILE_CANVAS)" not in CHART
    assert "volumeSeries" in CHART
    assert "shiftVisibleRangeOnNewBar: false" in CHART
    assert "Watch Trigger · Not an Order" in APP
    assert "MONITOR ${setup.direction} · NO ORDER" in CHART


def test_v24_version_and_cache():
    assert "2.4.0-stable-mobile-clear-execution" in MAIN
    assert 'CACHE_NAME = "tradeiq-v2.4-shell"' in SW
    assert "?v=24" in SW
