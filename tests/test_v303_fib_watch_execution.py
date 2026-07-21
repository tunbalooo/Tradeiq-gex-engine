from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.config import settings
from backend.models.schemas import Candle, EntryModelScore
from backend.services.decision_brain import decision_brain_service
from backend.services.setup_service import build_candidate_setup
from backend.services.storage_service import storage_service
from backend.services.trade_engine import TradeEngineService
from engine.entry_models import ModelContext, rank_entry_models
from engine.fib_pullback_continuation import analyze_fib_pullback_continuation

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _candle(at, open_, high, low, close, volume=100):
    return Candle(time=at, open=open_, high=high, low=low, close=close, volume=volume)


def _candidate(*, actionable=False, direction="LONG", entry=100.0, model_key="FIB_PULLBACK_CONTINUATION"):
    setup = build_candidate_setup()
    now = datetime.now(timezone.utc)
    model = EntryModelScore(
        key=model_key,
        name="Fib Pullback Continuation",
        direction=direction,
        score=88.0 if actionable else 66.0,
        eligible=True,
        trigger_price=entry,
        invalidation_price=95.0 if direction == "LONG" else 105.0,
    )
    return setup.model_copy(update={
        "setup_id": "fib-watch-test",
        "timestamp": now,
        "valid_until": now + timedelta(minutes=30),
        "direction": direction,
        "confidence": 70.0,
        "entry_valid": True,
        "actionable": actionable,
        "entry": entry,
        "stop_loss": 95.0 if direction == "LONG" else 105.0,
        "take_profit_1": 105.0 if direction == "LONG" else 95.0,
        "take_profit_2": 110.0 if direction == "LONG" else 90.0,
        "tp1_r": 1.0,
        "tp2_r": 2.0,
        "risk_reward": 2.0,
        "status": "WAITING_FOR_LIMIT" if actionable else "DEVELOPING",
        "order_state": "ARMED" if actionable else "PREVIEW_ONLY",
        "primary_entry_model": model.name,
        "primary_entry_model_key": model.key,
        "primary_model_score": model.score,
        "entry_model_scores": [model],
        "signals": {
            **setup.signals,
            "target_not_blocked": True,
            "trend_alignment": True,
            "fib_pullback_touched": actionable,
            "fib_pullback_rejection": actionable,
            "fib_pullback_entry_fresh": actionable,
        },
    })


def test_bullish_fib_pullback_uses_closed_rejection_and_body_midpoint():
    start = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    candles = [
        _candle(start, 115, 116, 113, 114),
        _candle(start + timedelta(minutes=1), 112, 113, 109, 110),
        _candle(start + timedelta(minutes=2), 108, 112, 107, 111.5),
    ]
    evidence = analyze_fib_pullback_continuation(
        candles, direction="LONG", swing_low=100, swing_high=120,
        current_price=112, atr=5, tick_size=.25,
    )
    assert evidence.zone_low == 107.75
    assert evidence.zone_high == 110.0
    assert evidence.touched is True
    assert evidence.rejection is True
    assert evidence.confirmed is True
    assert evidence.confirmation_entry == 109.75
    assert evidence.invalidation_price < evidence.zone_low


def test_bearish_fib_pullback_is_symmetric():
    start = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    candles = [
        _candle(start, 105, 107, 104, 106),
        _candle(start + timedelta(minutes=1), 108, 111, 107, 110),
        _candle(start + timedelta(minutes=2), 112, 113, 108, 108.5),
    ]
    evidence = analyze_fib_pullback_continuation(
        candles, direction="SHORT", swing_low=100, swing_high=120,
        current_price=108, atr=5, tick_size=.25,
    )
    assert evidence.zone_low == 110.0
    assert evidence.zone_high == 112.25
    assert evidence.touched is True
    assert evidence.rejection is True
    assert evidence.confirmed is True
    assert evidence.confirmation_entry == 110.25
    assert evidence.invalidation_price > evidence.zone_high


def test_fib_model_can_watch_before_confirmation_and_arm_after_confirmation():
    base_signals = {
        "trend_alignment": True,
        "gex_alignment": True,
        "liquidity_sweep": False,
        "displacement": True,
        "directional_fvg": False,
        "ordered_sequence": False,
        "supply_demand": True,
        "ote_overlap": False,
        "gex_ote_zone_cluster": True,
        "vwap_alignment": True,
        "target_not_blocked": True,
        "fib_pullback_impulse_quality": 1.0,
        "fib_pullback_touched": False,
        "fib_pullback_rejection": False,
        "fib_pullback_confirmed": False,
        "fib_pullback_entry_fresh": False,
    }
    context = ModelContext(
        direction="LONG", current_price=120, atr=10, proposed_entry=110,
        vwap=115, gamma_flip=112, selected_zone_low=106, selected_zone_high=111,
        ote_low=104, ote_high=108, fvg_low=None, fvg_high=None,
        signals=base_signals, structure={}, fib_pullback_low=108, fib_pullback_high=112,
        fib_pullback_confirmation_entry=None, fib_pullback_invalidation=105,
        volume_expansion=.7, session_quality=.8,
    )
    watching_rank = next(item for item in rank_entry_models(context) if item.key == "FIB_PULLBACK_CONTINUATION")
    assert watching_rank.eligible is True
    assert watching_rank.trigger_price == 110

    confirmed_context = replace(
        context,
        fib_pullback_confirmation_entry=113.0,
        signals={**base_signals, "fib_pullback_touched": True,
                 "fib_pullback_rejection": True, "fib_pullback_confirmed": True,
                 "fib_pullback_entry_fresh": True},
    )
    armed_rank = next(item for item in rank_entry_models(confirmed_context) if item.key == "FIB_PULLBACK_CONTINUATION")
    assert armed_rank.trigger_price == 113.0

    setup = build_candidate_setup().model_copy(update={
        "entry_valid": True, "entry": 113.0, "stop_loss": 105.0,
        "take_profit_1": 121.0, "take_profit_2": 129.0,
        "tp2_r": 2.0, "confidence": 80.0,
        "signals": {**base_signals, "target_not_blocked": True,
                    "fib_pullback_touched": True, "fib_pullback_rejection": True,
                    "fib_pullback_entry_fresh": True},
    })
    selected = decision_brain_service.select(setup, [armed_rank])
    assert selected.actionable is True


def test_watch_touch_is_visible_then_expires_only_after_confirmation_window(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    monkeypatch.setattr(storage_service, "transition", lambda *args, **kwargs: None)
    start = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])

    watching = service._start_watching(_candidate(), _candle(start, 102, 103, 101, 102))
    live_touch = _candle(start + timedelta(minutes=1), 101, 102, 99, 100.5)
    touched = service._advance_watching(watching, _candidate(), _candle(start, 102, 103, 101, 102), live_touch)
    assert touched.order_state == "WATCHING"
    assert touched.watch_phase == "TRIGGER_TOUCHED"
    assert touched.status == "CONFIRMING_LONG"
    assert touched.entry is None and touched.filled_at is None
    assert "not a fill" in touched.last_transition_reason.lower()

    # Fib Pullback Continuation owns a five-bar confirmation window. It must not
    # be cancelled by the old universal five-minute timeout.
    clock["now"] = start + timedelta(minutes=1 + settings.watch_confirmation_minutes + 1)
    still_confirming = service._advance_watching(touched, _candidate(), live_touch, live_touch)
    assert still_confirming.order_state == "WATCHING"
    assert still_confirming.watch_phase == "TRIGGER_TOUCHED"

    clock["now"] = touched.watch_confirmation_expires_at + timedelta(seconds=1)
    expired = service._advance_watching(touched.model_copy(update={"watch_touch_count": 2}), _candidate(), live_touch, live_touch)
    assert expired.order_state == "UNCONFIRMED_TOUCH"
    assert expired.outcome == "UNCONFIRMED_TOUCH"


def test_touch_then_closed_confirmation_arms_locked_plan(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    monkeypatch.setattr(storage_service, "transition", lambda *args, **kwargs: None)
    start = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])
    watching = service._start_watching(_candidate(), _candle(start, 102, 103, 101, 102))

    clock["now"] = start + timedelta(minutes=1)
    touched = service._advance_watching(
        watching, _candidate(), _candle(start, 102, 103, 101, 102),
        _candle(start + timedelta(minutes=1), 101, 102, 99, 100.5),
    )
    clock["now"] = start + timedelta(minutes=2)
    armed = service._advance_watching(
        touched, _candidate(actionable=True, entry=101.0),
        _candle(start + timedelta(minutes=1), 100, 103, 99, 102),
        _candle(start + timedelta(minutes=2), 102, 103, 101.5, 102.5),
    )
    assert armed.order_state == "WAITING_FOR_LIMIT"
    assert armed.entry == 101.0
    assert armed.watch_touch_at == touched.watch_touch_at
    assert armed.management_state == "LIMIT_ARMED"


def test_same_candle_pre_tp1_low_does_not_false_stop_new_breakeven():
    service = TradeEngineService()
    start = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    active = _candidate(actionable=True).model_copy(update={
        "order_state": "TP1_HIT", "status": "TP1_HIT", "entry": 100.0,
        "stop_loss": 95.0, "initial_stop_loss": 95.0, "active_stop_loss": 100.0,
        "take_profit_1": 105.0, "take_profit_2": 110.0,
        "armed_at": start - timedelta(minutes=2), "armed_candle_time": start - timedelta(minutes=2),
        "filled_at": start, "filled_candle_time": start,
        "active_stop_effective_candle_time": start, "runner_active": True,
    })
    candidate = _candidate(actionable=True)
    same_bar = _candle(start, 99, 106, 94, 104)
    still_running = service._advance(active, candidate, same_bar)
    assert still_running.order_state == "TP1_HIT"

    next_bar = _candle(start + timedelta(minutes=1), 103, 104, 99, 101)
    stopped = service._advance(still_running, candidate, next_bar)
    assert stopped.order_state == "STOPPED"
    assert stopped.outcome == "BREAKEVEN_AFTER_TP1"


def test_v303_frontend_and_version_contracts():
    assert "Fib Pullback Continuation" in ROOT.joinpath("engine/entry_models.py").read_text(encoding="utf-8")
    assert "TRIGGER_TOUCHED" in APP
    assert "Watch Touched · Awaiting Confirmation" in APP
    assert "TOUCHED · CONFIRM" in CHART
    assert 'primary_entry_model_key === "FIB_PULLBACK_CONTINUATION"' in CHART
    assert "fib_pullback_zone_low" in CHART and "fib_pullback_zone_high" in CHART
    assert "Structural Invalidation" in APP
    assert "3.0.3-fib-pullback-watch-execution" in MAIN
    assert 'CACHE_NAME = "tradeiq-v3.0.3-fib-pullback-watch-execution-shell"' in SW


def test_armed_limit_does_not_fill_from_pre_arm_live_range_but_fills_on_new_cross(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(storage_service, "transition", lambda *args, **kwargs: None)
    start = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    closed = _candle(start - timedelta(minutes=1), 102, 103, 101, 102)
    live_at_arm = _candle(start, 102, 103, 99, 102)
    candidate = _candidate(actionable=True, entry=100.0)

    armed = service._arm_candidate(candidate, closed, execution_candle=live_at_arm)
    unchanged = service._advance(armed, candidate, live_at_arm)
    assert unchanged.order_state == "WAITING_FOR_LIMIT"
    assert unchanged.filled_at is None

    crossed_after_arm = _candle(start, 102, 103, 99, 99.5)
    filled = service._advance(unchanged, candidate, crossed_after_arm)
    assert filled.order_state == "FILLED"
    assert filled.filled_at is not None


def test_watch_does_not_retroactively_touch_range_seen_before_monitoring(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    monkeypatch.setattr(storage_service, "transition", lambda *args, **kwargs: None)
    start = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    closed = _candle(start - timedelta(minutes=1), 102, 103, 101, 102)
    live_at_watch = _candle(start, 102, 103, 99, 102)
    candidate = _candidate(entry=100.0)

    watching = service._start_watching(candidate, closed, market_candle=live_at_watch)
    unchanged = service._advance_watching(watching, candidate, closed, live_at_watch)
    assert unchanged.status == "MONITORING_LONG"
    assert unchanged.watch_touch_at is None

    crossed_after_watch = _candle(start, 102, 103, 99, 99.5)
    touched = service._advance_watching(unchanged, candidate, closed, crossed_after_watch)
    assert touched.status == "CONFIRMING_LONG"
    assert touched.watch_phase == "TRIGGER_TOUCHED"
