from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.models.schemas import Candle
from backend.services.claude_analysis import SYSTEM_PROMPT
from backend.services.setup_service import build_candidate_setup
from backend.services.trade_engine import TradeEngineService

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CLAUDE = (ROOT / "backend" / "services" / "claude_analysis.py").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _candidate(**updates):
    setup = build_candidate_setup()
    payload = {
        "direction": "LONG",
        "confidence": 70.0,
        "entry_valid": True,
        "actionable": False,
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit_1": 105.0,
        "take_profit_2": 110.0,
        "risk_reward": 2.0,
        "status": "DEVELOPING",
        "order_state": "PREVIEW_ONLY",
        "target_sources": {"tp1": "GEX resistance", "tp2": "Supply zone"},
    }
    payload.update(updates)
    return setup.model_copy(update=payload)


def _candle(at, low=99.0, high=101.0, close=100.0):
    return Candle(time=at, open=100.0, high=high, low=low, close=close, volume=1)


def test_trade_lifecycle_records_authoritative_transition_reasons(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    start = datetime(2026, 7, 20, 2, 0, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(service, "_utcnow", lambda: clock["now"])

    watching = service._start_watching(_candidate(), _candle(start, low=101, high=102))
    assert watching.last_transition_from == "PREVIEW_ONLY"
    assert watching.last_transition_to == "WATCHING"
    assert "mandatory confirmations" in watching.last_transition_reason

    clock["now"] += timedelta(minutes=5)
    armed = service._advance_watching(
        watching,
        _candidate(actionable=True),
        _candle(clock["now"], low=101, high=102),
    )
    assert armed.last_transition_from == "WATCHING"
    assert armed.last_transition_to == "WAITING_FOR_LIMIT"
    assert "locked" in armed.last_transition_reason.lower()

    clock["now"] += timedelta(minutes=5)
    filled = service._advance(
        armed,
        _candidate(actionable=True),
        _candle(clock["now"], low=99, high=101),
    )
    assert filled.last_transition_from == "WAITING_FOR_LIMIT"
    assert filled.last_transition_to == "FILLED"
    assert "limit was filled" in filled.last_transition_reason.lower()


def test_claude_snapshot_and_prompt_are_lifecycle_aware():
    prompt = SYSTEM_PROMPT.lower()
    assert "your main job is to explain why" in prompt
    assert "waiting_for_limit" in prompt
    assert "filled" in prompt
    assert "invalidated, expired, unconfirmed_touch" in prompt
    assert '"lifecycle_event": lifecycle_event' in CLAUDE
    assert '"reason": setup_data.get("last_transition_reason")' in CLAUDE
    assert '"target_sources": setup_data.get("target_sources") or {}' in CLAUDE


def test_frontend_queues_claude_for_every_lifecycle_change():
    assert "function lifecycleEventKey(setup)" in APP
    assert "pendingLifecycle" in APP
    assert "transitionChanged ? 2500 : 30000" in APP
    assert "A fill/cancel/target can happen while Claude" in APP
    assert "EVENT|WHY" in APP
    assert "MISSING\\/NEXT" in APP
    assert "LEVELS" in APP


def test_v25_version_and_cache():
    assert "2.5.0-claude-lifecycle-explanations" in MAIN
    assert 'CACHE_NAME = "tradeiq-v2.5-shell"' in SW
    assert "?v=25" in SW
