from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.core.database import Base, SessionLocal, engine
from backend.core.time_utils import ensure_utc, utc_iso
from backend.models.db_models import TradeSetupRecord
from backend.services.storage_service import storage_service

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT.joinpath("backend/main.py").read_text(encoding="utf-8")
TIME_JS = ROOT.joinpath("frontend/time.js").read_text(encoding="utf-8")
APP = ROOT.joinpath("frontend/app.js").read_text(encoding="utf-8")
BOOT = ROOT.joinpath("frontend/boot.js").read_text(encoding="utf-8")
HTML = ROOT.joinpath("frontend/index.html").read_text(encoding="utf-8")
SW = ROOT.joinpath("frontend/service-worker.js").read_text(encoding="utf-8")


def test_v306_timezone_contract():
    assert "3.0.6-timezone-aware-history" in MAIN
    assert 'await loadScript("/static/time.js?v=306")' in BOOT
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in TIME_JS
    assert "offset-less API timestamps as UTC" in TIME_JS
    assert 'id="setupHistoryTimezone"' in HTML
    assert 'id="setupHistoryTimeHeader"' in HTML
    assert 'id="timeZonePreference"' in HTML
    assert "formatAppDateTime(item.updated_at)" in APP
    assert "tradeiq-v3.0.6-timezone-aware-history-shell" in SW


def test_naive_database_timestamp_is_interpreted_as_utc():
    naive = datetime(2026, 7, 21, 12, 25, 26)
    resolved = ensure_utc(naive)
    assert resolved.tzinfo == timezone.utc
    assert utc_iso(naive) == "2026-07-21T12:25:26Z"


def test_setup_history_returns_explicit_utc_timestamp():
    Base.metadata.create_all(bind=engine)
    setup_id = f"timezone-{uuid4()}"
    naive = datetime(2026, 7, 21, 12, 25, 26)
    with SessionLocal() as db:
        db.add(TradeSetupRecord(
            setup_id=setup_id,
            created_at=naive,
            updated_at=naive,
            symbol="NQ",
            direction="LONG",
            confidence=80,
            actionable=False,
            status="WATCHING",
            order_state="WATCHING",
            setup_snapshot={
                "watch_started_at": "2026-07-21T12:25:26Z",
                "primary_entry_model": "Timezone Test",
            },
        ))
        db.commit()

    try:
        rows = storage_service.recent_setups(500)
        row = next(item for item in rows if item["setup_id"] == setup_id)
        assert row["created_at"].endswith("Z")
        assert row["updated_at"] == "2026-07-21T12:25:26Z"
    finally:
        with SessionLocal() as db:
            record = db.query(TradeSetupRecord).filter(TradeSetupRecord.setup_id == setup_id).one_or_none()
            if record is not None:
                db.delete(record)
                db.commit()
