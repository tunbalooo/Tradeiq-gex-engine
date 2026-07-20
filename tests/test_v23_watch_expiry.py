from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.models.schemas import Candle
from backend.services.setup_service import build_candidate_setup
from backend.services.trade_engine import TradeEngineService

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _candidate(**updates):
    setup = build_candidate_setup()
    base = {
        "symbol": "NQ",
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
        "atr": 4.0,
        "cluster_low": 99.0,
        "cluster_high": 101.0,
        "selected_zone_timeframe": "5m",
    }
    base.update(updates)
    return setup.model_copy(update=base)


def _candle(at: datetime) -> Candle:
    return Candle(time=at, open=104, high=105, low=103, close=104, volume=1)


def test_watch_deadline_does_not_move_during_refresh(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    start = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])

    watching = service._start_watching(_candidate(), _candle(start))
    original_expiry = watching.watch_expires_at
    assert watching.watch_started_at == start
    assert original_expiry == start + timedelta(minutes=30)

    for minutes in (2, 7, 14, 22, 29):
        clock["now"] = start + timedelta(minutes=minutes)
        watching = service._advance_watching(
            watching,
            _candidate(confidence=62.0 + minutes / 10, entry=103.0),
            _candle(clock["now"]),
        )
        assert watching.order_state == "WATCHING"
        assert watching.entry is None
        assert watching.watch_trigger == 100.0
        assert watching.watch_started_at == start
        assert watching.watch_expires_at == original_expiry
        assert watching.valid_until == original_expiry


def test_watch_expires_before_late_confirmation(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    start = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])

    watching = service._start_watching(_candidate(), _candle(start))
    clock["now"] = watching.watch_expires_at
    expired = service._advance_watching(
        watching,
        _candidate(actionable=True, confidence=88.0),
        _candle(clock["now"]),
    )

    assert expired.order_state == "EXPIRED"
    assert expired.outcome == "WATCH_EXPIRED"
    assert expired.closed_at == clock["now"]
    assert expired.armed_at is None


def test_same_expired_candidate_is_not_recreated(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    start = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])

    watching = service._start_watching(_candidate(), _candle(start))
    clock["now"] = watching.watch_expires_at + timedelta(seconds=1)
    expired = service._advance_watching(watching, _candidate(), _candle(clock["now"]))
    assert expired.order_state == "EXPIRED"

    suppressed = service._evaluate_candidate(_candidate(), _candle(clock["now"]))
    assert suppressed.order_state == "PREVIEW_ONLY"
    assert suppressed.status == "WATCH_EXPIRED"

    # A materially different entry creates a genuinely new watch with a new deadline.
    clock["now"] += timedelta(minutes=2)
    replacement = service._evaluate_candidate(_candidate(entry=110.0), _candle(clock["now"]))
    assert replacement.order_state == "WATCHING"
    assert replacement.watch_started_at == clock["now"]
    assert replacement.watch_expires_at == clock["now"] + timedelta(minutes=30)


def test_confirmed_plan_keeps_watch_audit_times(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    start = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])

    watching = service._start_watching(_candidate(), _candle(start))
    clock["now"] = start + timedelta(minutes=10)
    armed = service._advance_watching(
        watching,
        _candidate(actionable=True, confidence=80.0, entry=101.0),
        _candle(clock["now"]),
    )

    assert armed.order_state == "WAITING_FOR_LIMIT"
    assert armed.watch_started_at == start
    assert armed.watch_expires_at == start + timedelta(minutes=30)
    assert armed.valid_until == clock["now"] + timedelta(minutes=30)


def test_v23_frontend_and_version_use_immutable_watch_expiry():
    assert "setup.watch_expires_at || setup.valid_until" in APP
    assert "Watch expired — waiting for a new candidate" in APP
    assert "2.3.0-fixed-watch-expiry" in MAIN
    assert 'CACHE_NAME = "tradeiq-v2.3-shell"' in SW
    assert "?v=23" in SW
