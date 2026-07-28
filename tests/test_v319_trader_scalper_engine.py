from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.config import settings
from backend.models.schemas import Candle
from backend.services.setup_service import build_candidate_setup
from backend.services.trade_engine import TradeEngineService
from engine.adaptive_execution import select_execution

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _candle(at: datetime, close: float = 100.0) -> Candle:
    return Candle(time=at, open=close, high=close + 1, low=close - 1, close=close, volume=100)


def _watch_candidate():
    base = build_candidate_setup()
    key = base.primary_entry_model_key or "VWAP_RECLAIM"
    return base.model_copy(update={
        "direction": "LONG",
        "confidence": 70.0,
        "entry_valid": True,
        "actionable": False,
        "entry": 100.0,
        "stop_loss": 96.0,
        "take_profit_1": 103.2,
        "take_profit_2": 106.0,
        "tp1_r": 0.8,
        "tp2_r": 1.5,
        "risk_reward": 1.5,
        "primary_model_score": 75.0,
        "primary_entry_model_key": key,
        "signals": {
            **base.signals,
            "target_not_blocked": True,
            "model_confirmations": {
                **(base.signals.get("model_confirmations") or {}),
                key: {
                    "confirmed": False,
                    "label": "fast scalp confirmation",
                    "evidence": [],
                    "missing": ["micro shift"],
                    "window_bars": 3,
                },
            },
        },
    })


def test_scalper_mode_is_default_and_uses_fast_active_limits():
    assert settings.scalper_mode_enabled is True
    assert settings.active_setup_expiry_minutes == 8
    assert settings.active_watch_confirmation_minutes == 2
    assert settings.active_confirmation_bar_minutes == 1
    assert settings.active_direction_switch_confirm_bars == 2
    assert settings.active_min_tp1_r == 0.8
    assert settings.active_min_tp2_r == 1.5


def test_scalper_watch_expires_in_minutes_not_hours(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    start = datetime(2026, 7, 26, 14, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "_utcnow", lambda: start)

    watching = service._start_watching(_watch_candidate(), _candle(start))

    assert watching.watch_expires_at == start + timedelta(minutes=8)
    assert watching.valid_until == watching.watch_expires_at


def test_scalper_confirmation_window_uses_one_minute_bars():
    service = TradeEngineService()
    candidate = _watch_candidate()
    assert service._confirmation_window_minutes(candidate) == 3


def test_scalper_execution_accepts_realistic_one_point_five_r_target():
    decision = select_execution(
        model_key="VWAP_RECLAIM",
        direction="LONG",
        current_price=100.25,
        ideal_entry=100.0,
        atr=2.0,
        tick_size=0.25,
        model_confirmed=True,
        entry_valid=True,
        target_not_blocked=True,
        tp1=103.2,
        tp2=106.0,
        tp2_r=1.5,
        stop_loss=96.5,
        minimum_tp2_r=1.5,
        scalper_mode=True,
    )
    assert decision.executable is True
    assert decision.execution_type == "MARKET"


def test_candidate_compares_long_and_short_and_marks_scalper_context():
    setup = build_candidate_setup()
    assert setup.signals["engine_mode"] == "SCALPER"
    assert setup.signals["execution_timeframe"] == "1m"
    assert setup.signals["scalp_dual_direction_scan"] is True
    assert {"LONG", "SHORT"}.issubset(set(setup.signals["scalp_side_scores"]))


def test_frontend_displays_execution_first_scalp_readiness_and_block_reason():
    assert "Scalp Readiness" in APP
    assert "scanBlockReason" in APP
    assert "Location ${qualityView.location.toFixed(0)} · Confirm ${qualityView.confirmation.toFixed(0)} · Execute" in APP
    assert "3.1.9-trader-scalper-engine" in MAIN
    assert "tradeiq-v3.1.9-trader-scalper-engine-shell" in SW


def test_scalper_cluster_uses_active_confidence_floor(monkeypatch):
    from engine.institutional_cluster import build_cluster_score

    monkeypatch.setattr(settings, "scalper_mode_enabled", True)
    monkeypatch.setattr(settings, "setup_confidence_floor", 99.0)
    monkeypatch.setattr(settings, "scalp_setup_confidence_floor", 35.0)
    result = build_cluster_score(
        {
            "gex_alignment": True,
            "supply_demand": True,
            "ote_overlap": True,
            "liquidity_sweep": True,
        },
        [],
        1.0,
    )
    assert result["tier"] == "HIGH_PRIORITY_4_PLUS"
    assert result["minimum_confidence"] == 35.0


def test_settings_endpoint_reports_active_scalper_values():
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as client:
        response = client.get("/api/settings")
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine_mode"] == "SCALPER"
    assert payload["scalper_mode_enabled"] is True
    assert payload["expiry_minutes"] == 8
    assert payload["watch_confirmation_minutes"] == 2
    assert payload["minimum_tp1_r"] == 0.8
    assert payload["minimum_tp2_r"] == 1.5


def test_v319_assets_are_cache_busted():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    boot = (ROOT / "frontend" / "boot.js").read_text(encoding="utf-8")
    assert "/static/styles.css?v=319" in index
    assert "/static/boot.js?v=319" in index
    assert "/static/time.js?v=319" in boot
    assert "/static/trading_chart.js?v=319" in boot
    assert "/static/app.js?v=319" in boot
    assert "/static/app.js?v=319" in SW
