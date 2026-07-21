from datetime import datetime, timezone
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
        "direction": "LONG",
        "confidence": 62.0,
        "entry_valid": True,
        "actionable": False,
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit_1": 105.0,
        "take_profit_2": 110.0,
        "risk_reward": 2.0,
        "status": "DEVELOPING",
        "order_state": "PREVIEW_ONLY",
    }
    base.update(updates)
    return setup.model_copy(update=base)


def test_watching_entry_stays_fixed_until_confirmation(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    candle = Candle(time=datetime.now(timezone.utc), open=100, high=101, low=99, close=100, volume=1)

    watching = service._start_watching(_candidate(entry=100.0), candle)
    refreshed = service._advance_watching(watching, _candidate(entry=103.0, confidence=66.0), candle)

    assert refreshed.order_state == "WATCHING"
    assert refreshed.status == "MONITORING_LONG"
    assert refreshed.watch_phase == "WAITING_FOR_PRICE"
    assert refreshed.entry is None
    assert refreshed.watch_trigger == 100.0
    assert refreshed.confidence == 66.0


def test_watching_promotes_to_locked_limit(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    candle = Candle(time=datetime.now(timezone.utc), open=100, high=101, low=99, close=100, volume=1)

    watching = service._start_watching(_candidate(entry=100.0), candle)
    confirmed = _candidate(
        actionable=True,
        entry=102.0,
        stop_loss=97.0,
        take_profit_1=107.0,
        take_profit_2=112.0,
    )
    armed = service._advance_watching(watching, confirmed, candle)

    assert armed.order_state == "WAITING_FOR_LIMIT"
    assert armed.setup_id == watching.setup_id
    assert armed.armed_at is not None
    assert armed.entry == 102.0
    assert armed.stop_loss == 97.0


def test_frontend_shows_watch_line_but_hides_risk_plan():
    assert "function hasWatchingPlan(setup)" in APP
    assert "function hasWatchingPlan(setup)" in CHART
    assert "MONITORING ${setup.direction}" in APP
    assert "Watch Trigger · Not an Order" in APP
    assert "MONITOR ${setup.direction} · NO ORDER" in CHART
    assert "else if (overlays.trade && hasLockedTradePlan(setup))" in CHART
    assert "if (overlays.trade && hasLockedTradePlan(setup))" in CHART


def test_v21_version_and_cache_are_visible():
    assert "2.1.0-watching-to-limit" in MAIN
    assert "tradeiq-v2.1-shell" in SW
    assert "?v=21" in SW
