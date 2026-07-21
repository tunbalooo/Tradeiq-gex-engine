from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete

from backend.core.database import SessionLocal
from backend.models.db_models import TradeSetupRecord
from backend.models.schemas import Candle, EntryModelScore
from backend.services.decision_brain import decision_brain_service
from backend.services.market_data import _sanitize_candles
from backend.services.setup_service import build_candidate_setup
from backend.services.storage_service import storage_service
from backend.services.trade_engine import TradeEngineService

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _candle(time: datetime, open_: float, high: float, low: float, close: float, volume: int = 100) -> Candle:
    return Candle(time=time, open=open_, high=high, low=low, close=close, volume=volume)


def _model(key: str, name: str, direction: str, score: float, trigger: float) -> EntryModelScore:
    return EntryModelScore(
        key=key,
        name=name,
        direction=direction,
        score=score,
        eligible=True,
        trigger_price=trigger,
        invalidation_price=trigger - 10 if direction == "LONG" else trigger + 10,
    )


def _candidate(direction: str = "LONG", key: str = "OTE_RETRACEMENT", name: str = "OTE Retracement", score: float = 80.0, entry: float = 100.0, actionable: bool = False):
    setup = build_candidate_setup()
    model = _model(key, name, direction, score, entry)
    now = datetime.now(timezone.utc)
    return setup.model_copy(update={
        "setup_id": f"test-{direction.lower()}-{key.lower()}",
        "timestamp": now,
        "valid_until": now + timedelta(minutes=30),
        "direction": direction,
        "confidence": 62.0,
        "confidence_grade": "C",
        "entry_valid": True,
        "actionable": actionable,
        "entry": entry,
        "stop_loss": entry - 10 if direction == "LONG" else entry + 10,
        "take_profit_1": entry + 10 if direction == "LONG" else entry - 10,
        "take_profit_2": entry + 20 if direction == "LONG" else entry - 20,
        "tp1_r": 1.0,
        "tp2_r": 2.0,
        "risk_reward": 2.0,
        "status": "WAITING_FOR_LIMIT" if actionable else "DEVELOPING",
        "order_state": "ARMED" if actionable else "PREVIEW_ONLY",
        "primary_entry_model": name,
        "primary_entry_model_key": key,
        "primary_model_score": score,
        "entry_model_scores": [model],
        "signals": {
            **setup.signals,
            "target_not_blocked": True,
            "trend_alignment": True,
            "ote_overlap": True,
            "supply_demand": True,
            "displacement": True,
            "ordered_sequence": False,
            "liquidity_sweep": False,
            "gex_alignment": False,
            "gex_ote_zone_cluster": False,
        },
    })


def test_ote_can_arm_without_unrelated_universal_liquidity_gate():
    setup = _candidate(score=91.0)
    ranked = setup.entry_model_scores
    selected = decision_brain_service.select(setup, ranked)

    assert selected.actionable is True
    assert selected.order_state == "ARMED"
    assert selected.signals["entry_model_confirmed"] is True
    # These were part of the previous universal gate and must not block OTE.
    assert selected.signals["liquidity_sweep"] is False
    assert selected.signals["ordered_sequence"] is False
    assert selected.signals["gex_alignment"] is False


def test_model_score_can_start_monitoring_before_old_global_confidence_threshold(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    candidate = _candidate(score=66.0).model_copy(update={"confidence": 46.0})
    candle = _candle(datetime.now(timezone.utc), 110, 112, 108, 111)

    watching = service._evaluate_candidate(candidate, candle)

    assert watching.order_state == "WATCHING"
    assert watching.watch_trigger == candidate.entry
    assert watching.actionable is False


def test_direction_switch_requires_distinct_closed_candles(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    monkeypatch.setattr(storage_service, "transition", lambda *args, **kwargs: None)

    start = datetime.now(timezone.utc)
    watching = _candidate(direction="LONG", score=70.0, entry=90.0).model_copy(update={
        "order_state": "WATCHING",
        "status": "MONITORING_LONG",
        "watch_trigger": 90.0,
        "watch_started_at": start,
        "watch_expires_at": start + timedelta(minutes=30),
        "last_processed_candle_time": start - timedelta(minutes=1),
    })
    opposite = _candidate(
        direction="SHORT",
        key="TREND_CONTINUATION",
        name="Trend Continuation",
        score=70.0,
        entry=120.0,
    )

    first_bar = _candle(start, 110, 112, 108, 111)
    first = service._advance_watching(watching, opposite, first_bar)
    repeated = service._advance_watching(first, opposite, first_bar)
    second_bar = _candle(start + timedelta(minutes=1), 111, 113, 109, 112)
    confirmed = service._advance_watching(repeated, opposite, second_bar)

    assert first.order_state == "WATCHING"
    assert repeated.order_state == "WATCHING"
    assert confirmed.order_state == "INVALIDATED"
    assert confirmed.outcome == "OPPOSITE_SETUP"


def test_latest_live_giant_wick_is_removed_not_automatically_appended():
    start = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    candles = []
    price = 28800.0
    for index in range(35):
        candles.append(_candle(start + timedelta(minutes=index), price, price + 8, price - 7, price + 1))
        price += 1
    malformed_time = start + timedelta(minutes=35)
    candles.append(_candle(malformed_time, price, price + 600, price - 5, price + 2))

    clean = _sanitize_candles(candles)

    assert malformed_time not in {item.time for item in clean}
    assert clean[-1].time == start + timedelta(minutes=34)


def test_setup_history_hides_transient_preview_rows():
    now = datetime.now(timezone.utc)
    preview_id = "v302-preview-hidden"
    watching_id = "v302-watching-visible"
    with SessionLocal() as db:
        db.execute(delete(TradeSetupRecord).where(TradeSetupRecord.setup_id.in_([preview_id, watching_id])))
        db.add(TradeSetupRecord(
            setup_id=preview_id,
            created_at=now,
            updated_at=now,
            symbol="NQ",
            direction="LONG",
            confidence=55,
            order_state="PREVIEW_ONLY",
            status="SCANNING",
            setup_snapshot={"primary_entry_model": "OTE Retracement"},
        ))
        db.add(TradeSetupRecord(
            setup_id=watching_id,
            created_at=now,
            updated_at=now + timedelta(seconds=1),
            symbol="NQ",
            direction="LONG",
            confidence=65,
            order_state="WATCHING",
            status="MONITORING_LONG",
            setup_snapshot={"primary_entry_model": "OTE Retracement", "watch_started_at": now.isoformat(), "watch_trigger": 28781.0},
        ))
        db.commit()

    try:
        ids = {item["setup_id"] for item in storage_service.recent_setups(limit=100)}
        assert watching_id in ids
        assert preview_id not in ids
    finally:
        with SessionLocal() as db:
            db.execute(delete(TradeSetupRecord).where(TradeSetupRecord.setup_id.in_([preview_id, watching_id])))
            db.commit()


def test_clean_chart_mode_is_default_and_v302_assets_are_versioned():
    assert "overlays: { clean: true" in APP
    assert 'data-overlay="clean"' in INDEX
    assert "cleanPriorityZones" in CHART
    assert "systemLabelPrices" in CHART
    assert "3.0.2-entry-chart-stability" in MAIN
    assert 'CACHE_NAME = "tradeiq-v3.0.2-entry-chart-stability-shell"' in SW
