from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete

from backend.core.database import Base, SessionLocal, engine
from backend.models.db_models import TradeSetupRecord
from backend.models.schemas import Candle
from backend.services.setup_service import build_candidate_setup
from backend.services.storage_service import storage_service
from backend.services.trade_engine import TradeEngineService

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


def test_decision_brain_separates_location_confirmation_and_trade_quality():
    setup = build_candidate_setup()
    assert setup.trigger_entry_model
    assert setup.trigger_entry_model_key
    assert setup.thesis_fingerprint and len(setup.thesis_fingerprint) == 20
    assert setup.structure_event_key
    assert 0 <= setup.location_quality_score <= 100
    assert 0 <= setup.confirmation_quality_score <= 100
    assert 0 <= setup.execution_quality_score <= 100
    if setup.actionable:
        assert setup.trade_quality_score > 0
        assert setup.trade_grade != "—"
        assert setup.quality_stage == "EXECUTABLE"
    else:
        assert setup.trade_quality_score == 0
        assert setup.trade_grade == "—"
        assert setup.quality_stage in {"LOCATION_ONLY", "CONFIRMED_NO_EXECUTION"}


def test_trade_and_scanner_logs_are_separate_and_scans_are_deduplicated():
    Base.metadata.create_all(bind=engine)
    now = datetime.now(timezone.utc)
    scan_old = f"scan-old-{uuid4()}"
    scan_new = f"scan-new-{uuid4()}"
    trade_id = f"trade-{uuid4()}"
    fingerprint = f"same-thesis-{uuid4()}"
    ids = [scan_old, scan_new, trade_id]
    with SessionLocal() as db:
        db.add(TradeSetupRecord(
            setup_id=scan_old, created_at=now, updated_at=now,
            symbol="NQ", direction="SHORT", confidence=80,
            order_state="WATCHING", status="MONITORING_SHORT",
            setup_snapshot={
                "watch_started_at": now.isoformat(),
                "thesis_fingerprint": fingerprint,
                "trigger_entry_model": "Liquidity Sweep + Structure Shift",
                "location_quality_score": 88,
                "confirmation_quality_score": 40,
            },
        ))
        db.add(TradeSetupRecord(
            setup_id=scan_new, created_at=now, updated_at=now + timedelta(seconds=5),
            symbol="NQ", direction="SHORT", confidence=82,
            order_state="EXPIRED", status="EXPIRED", outcome="WATCH_EXPIRED",
            setup_snapshot={
                "watch_started_at": now.isoformat(),
                "thesis_fingerprint": fingerprint,
                "trigger_entry_model": "Liquidity Sweep + Structure Shift",
                "location_quality_score": 88,
                "confirmation_quality_score": 55,
            },
        ))
        db.add(TradeSetupRecord(
            setup_id=trade_id, created_at=now, updated_at=now + timedelta(seconds=10),
            armed_at=now, filled_at=now, closed_at=now + timedelta(minutes=5),
            symbol="NQ", direction="LONG", confidence=86,
            actionable=False, entry=100, stop_loss=95, take_profit_1=107, take_profit_2=110,
            order_state="STOPPED", status="STOPPED", outcome="STOPPED", result_r=-1,
            setup_snapshot={
                "armed_at": now.isoformat(),
                "filled_at": now.isoformat(),
                "trigger_entry_model": "OTE Retracement",
                "primary_entry_model": "Institutional Confluence Cluster",
                "trade_grade": "B+",
                "trade_quality_score": 79,
            },
        ))
        db.commit()

    try:
        trades = storage_service.recent_trades(500)
        scans = storage_service.recent_scans(500)
        assert trade_id in {row["setup_id"] for row in trades}
        assert scan_old not in {row["setup_id"] for row in trades}
        selected_scans = [row for row in scans if row.get("thesis_fingerprint") == fingerprint]
        assert len(selected_scans) == 1
        assert selected_scans[0]["setup_id"] == scan_new
        assert selected_scans[0]["trigger_entry_model"] == "Liquidity Sweep + Structure Shift"
    finally:
        with SessionLocal() as db:
            db.execute(delete(TradeSetupRecord).where(TradeSetupRecord.setup_id.in_(ids)))
            db.commit()


def test_stopped_thesis_cannot_reenter_until_fingerprint_changes(monkeypatch):
    service = TradeEngineService()
    monkeypatch.setattr(service, "_market_gate", lambda: (True, None))
    setup = build_candidate_setup().model_copy(update={
        "direction": "LONG",
        "confidence": 80.0,
        "primary_model_score": 80.0,
        "entry_valid": True,
        "actionable": False,
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit_1": 107.0,
        "take_profit_2": 112.0,
        "tp2_r": 2.4,
        "thesis_fingerprint": "locked-thesis",
        "structure_event_key": "event-one",
        "trigger_entry_model": "Liquidity Sweep + Structure Shift",
    })
    stopped = setup.model_copy(update={"order_state": "STOPPED", "outcome": "STOPPED"})
    service._remember_terminal_thesis(stopped)
    candle = Candle(
        time=datetime.now(timezone.utc), open=101, high=102, low=99, close=101, volume=1,
    )

    blocked = service._evaluate_candidate(setup, candle)
    assert blocked.order_state == "PREVIEW_ONLY"
    assert blocked.status == "THESIS_LOCKED"
    assert "new sweep" in blocked.execution_reason.lower()

    new_event = setup.model_copy(update={
        "thesis_fingerprint": "new-thesis",
        "structure_event_key": "event-two",
    })
    replacement = service._evaluate_candidate(new_event, candle)
    assert replacement.order_state == "WATCHING"


def test_v316_frontend_has_trade_log_scanner_log_and_quality_labels():
    assert "Trade Log · Published Entries" in INDEX
    assert "Scanner Log · Unique Theses" in INDEX
    assert 'fetch("/api/scans/history")' in APP
    assert "Location Grade" in INDEX
    assert "trade_quality_score" in APP
    assert "3.1.6-audit-quality-lifecycle" in MAIN
