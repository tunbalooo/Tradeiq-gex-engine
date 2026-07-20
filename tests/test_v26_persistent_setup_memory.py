from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.core.database import Base, engine
from backend.main import app
from backend.services.setup_service import build_candidate_setup
from backend.services.storage_service import storage_service
from backend.services.trade_engine import TradeEngineService

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
CLAUDE = (ROOT / "backend" / "services" / "claude_analysis.py").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _active_setup(setup_id: str):
    now = datetime.now(timezone.utc)
    candidate = build_candidate_setup()
    return candidate.model_copy(update={
        "setup_id": setup_id,
        "timestamp": now,
        "direction": "LONG",
        "order_state": "WATCHING",
        "status": "MONITORING_LONG",
        "actionable": False,
        "watch_trigger": 100.0,
        "entry": None,
        "stop_loss": None,
        "take_profit_1": None,
        "take_profit_2": None,
        "last_transition_from": "PREVIEW_ONLY",
        "last_transition_to": "WATCHING",
        "last_transition_reason": "Monitoring a persisted long candidate.",
        "last_transition_at": now,
        "last_transition_price": 100.0,
    })


def test_storage_restores_active_setup_and_timeline():
    Base.metadata.create_all(bind=engine)
    setup_id = f"v26-{uuid4()}"
    setup = _active_setup(setup_id)
    storage_service.save_setup(setup)
    storage_service.transition(
        setup, "PREVIEW_ONLY", "WATCHING", 100.0, setup.timestamp,
        "Monitoring a persisted long candidate.", "warning",
    )

    restored = storage_service.load_active_setup(symbol=setup.symbol)
    assert restored is not None
    assert restored.setup_id == setup_id
    assert restored.order_state == "WATCHING"
    assert restored.watch_trigger == 100.0

    timeline = storage_service.setup_timeline(setup_id)
    assert timeline[-1]["previous_state"] == "PREVIEW_ONLY"
    assert timeline[-1]["new_state"] == "WATCHING"
    assert "persisted long" in timeline[-1]["detail"]


def test_trade_engine_rehydrates_without_replacing_setup(monkeypatch):
    setup = _active_setup(f"restore-{uuid4()}")
    service = TradeEngineService()
    monkeypatch.setattr(storage_service, "load_active_setup", lambda symbol=None: setup)

    restored = service.restore_from_storage()

    assert restored is not None
    assert service.current_setup().setup_id == setup.setup_id
    assert service.snapshot().restored_setup_id == setup.setup_id
    assert service.snapshot().restored_at is not None


def test_timeline_api_returns_persisted_events():
    Base.metadata.create_all(bind=engine)
    setup_id = f"api-v26-{uuid4()}"
    setup = _active_setup(setup_id)
    storage_service.save_setup(setup)
    storage_service.transition(setup, "PREVIEW_ONLY", "WATCHING", 100.0, setup.timestamp, "API timeline event.")

    with TestClient(app) as client:
        response = client.get(f"/api/setups/{setup_id}/timeline")
    assert response.status_code == 200
    payload = response.json()
    assert payload["setup_id"] == setup_id
    assert payload["events"][-1]["new_state"] == "WATCHING"


def test_v26_ui_claude_version_and_living_spec():
    assert 'id="setupTimeline"' in INDEX
    assert 'id="chartSetupTimeline"' in INDEX
    assert "function loadSetupTimeline(setup, force = false)" in APP_JS
    assert "/timeline?limit=20" in APP_JS
    assert '"lifecycle_timeline": lifecycle_timeline' in CLAUDE
    assert "2.6.0-persistent-setup-memory" in MAIN
    assert 'CACHE_NAME = "tradeiq-v2.6-shell"' in SW
    assert (ROOT / "TRADEIQ_INSTITUTIONAL_ENTRY_ENGINE_SPEC.md").exists()
