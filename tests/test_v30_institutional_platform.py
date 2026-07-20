from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.models.schemas import Candle
from backend.services.instruments import instrument_registry
from backend.services.setup_service import _stable_fallback_gex, build_candidate_setup, clear_fallback_gex_cache
from backend.services.trade_engine import TradeEngineService
from engine.institutional_confidence import CATEGORY_WEIGHTS

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _candidate(**updates):
    setup = build_candidate_setup()
    base = {
        "direction": "LONG",
        "confidence": 90.0,
        "confidence_grade": "A+",
        "entry_valid": True,
        "actionable": True,
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit_1": 105.0,
        "take_profit_2": 110.0,
        "tp1_r": 1.0,
        "tp2_r": 2.0,
        "risk_reward": 2.0,
        "status": "WAITING_FOR_LIMIT",
        "order_state": "ARMED",
        "primary_entry_model": "Liquidity Sweep + Structure Shift",
        "primary_entry_model_key": "LIQUIDITY_SWEEP_MSS",
        "primary_model_score": 92.0,
    }
    base.update(updates)
    return setup.model_copy(update=base)


def test_decision_brain_ranks_models_and_confidence_is_transparent():
    setup = build_candidate_setup()
    assert setup.primary_entry_model
    assert setup.primary_entry_model_key
    assert len(setup.entry_model_scores) >= 12
    assert setup.entry_model_scores == sorted(
        setup.entry_model_scores,
        key=lambda item: (not item.eligible, -item.score, item.priority, item.name),
    )
    assert setup.confidence_grade in {"A+", "A", "B+", "B", "C", "AVOID"}
    assert setup.institutional_confidence_maximums == CATEGORY_WEIGHTS
    assert round(sum(setup.institutional_confidence_maximums.values()), 1) == 100.0


def test_fallback_gex_levels_stay_fixed_until_cache_is_cleared():
    profile = instrument_registry.active
    clear_fallback_gex_cache(profile.symbol)
    first = _stable_fallback_gex(25000.0, profile)
    second = _stable_fallback_gex(25200.0, profile)
    assert second.gamma_flip == first.gamma_flip
    assert second.call_wall == first.call_wall
    assert second.put_wall == first.put_wall

    clear_fallback_gex_cache(profile.symbol)
    refreshed = _stable_fallback_gex(25200.0, profile)
    assert refreshed.updated_at >= first.updated_at


def test_tp1_secures_partial_and_moves_runner_to_break_even(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    t0 = datetime.now(timezone.utc)
    armed_candle = Candle(time=t0, open=101, high=102, low=100.5, close=101, volume=100)
    armed = service._arm_candidate(_candidate(), armed_candle)

    fill_candle = Candle(time=t0 + timedelta(minutes=1), open=101, high=101.5, low=99.5, close=100.5, volume=100)
    filled = service._advance(armed, _candidate(), fill_candle)
    assert filled.order_state == "FILLED"
    assert filled.active_stop_loss == 95.0

    tp1_candle = Candle(time=t0 + timedelta(minutes=2), open=102, high=105.5, low=101, close=105, volume=100)
    tp1 = service._advance(filled, _candidate(), tp1_candle)
    assert tp1.order_state == "TP1_HIT"
    assert tp1.active_stop_loss == 100.0
    assert tp1.breakeven_at is not None
    assert tp1.runner_active is True
    assert any(action["action"] == "MOVE_TO_BREAKEVEN" for action in tp1.management_actions)

    breakeven_candle = Candle(time=t0 + timedelta(minutes=3), open=101, high=102, low=99.75, close=100, volume=100)
    closed = service._advance(tp1, _candidate(), breakeven_candle)
    assert closed.order_state == "STOPPED"
    assert closed.outcome == "BREAKEVEN_AFTER_TP1"
    assert service._result_r(closed) == 0.5


def test_v30_api_and_interface_are_exposed():
    with TestClient(app) as client:
        brain = client.get("/api/decision-brain")
        models = client.get("/api/entry-models")
        analytics = client.get("/api/analytics/summary")
    assert brain.status_code == 200
    assert models.status_code == 200
    assert analytics.status_code == 200
    assert "models" in brain.json()
    assert "model_leaderboard" in analytics.json()

    assert "3.0.0-institutional-decision-platform" in MAIN
    assert 'CACHE_NAME = "tradeiq-v3.0-shell"' in SW
    assert 'id="setupModelRanking"' in INDEX
    assert 'id="modelLeaderboard"' in INDEX
    assert "function renderModelRanking" in APP
