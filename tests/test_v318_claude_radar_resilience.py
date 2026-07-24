import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.main import app
from backend.services import claude_analysis as claude_module
from backend.services import multi_market_monitor as radar_module
from backend.services.claude_analysis import ClaudeAnalysisService
from backend.services.instruments import instrument_registry
from backend.services.market_data import market_data_service
from backend.services.multi_market_monitor import MultiMarketMonitorService
from backend.services.setup_service import build_candidate_setup

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


class _TextBlock:
    text = "EVENT: Test lifecycle\nWHY: Deterministic engine state.\nRISK: Read-only."


class _Message:
    content = [_TextBlock()]
    model = "claude-test-model"


class _Messages:
    calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        return _Message()


class _FakeAnthropic:
    shared_messages = _Messages()

    def __init__(self, **_kwargs):
        self.messages = self.shared_messages

    async def close(self):
        return None


def test_claude_json_fallback_shares_cache(monkeypatch):
    with TestClient(app):
        service = ClaudeAnalysisService()
        _FakeAnthropic.shared_messages.calls = 0
        monkeypatch.setattr(claude_module, "AsyncAnthropic", _FakeAnthropic)
        monkeypatch.setattr(settings, "claude_analysis_enabled", True)
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(settings, "anthropic_model", "claude-test-model")

        first = asyncio.run(service.analyze(force=False))
        second = asyncio.run(service.analyze(force=False))

    assert first["cached"] is False
    assert second["cached"] is True
    assert first["text"].startswith("EVENT:")
    assert _FakeAnthropic.shared_messages.calls == 1
    assert service.status()["operational"] is True


def test_claude_sse_sends_immediate_flush_and_heartbeat(monkeypatch):
    with TestClient(app):
        service = ClaudeAnalysisService()
        monkeypatch.setattr(claude_module, "AsyncAnthropic", _FakeAnthropic)
        monkeypatch.setattr(settings, "claude_analysis_enabled", True)
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

        async def read_prefix():
            stream = service.stream(force=False)
            first = await anext(stream)
            second = await anext(stream)
            await stream.aclose()
            return first, second

        padding, heartbeat = asyncio.run(read_prefix())

    assert padding.startswith(": ")
    assert len(padding) >= 2048
    assert "event: heartbeat" in heartbeat


def test_claude_json_endpoint_fails_safely_when_disabled():
    with TestClient(app) as client:
        response = client.post("/api/ai/analysis")
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"].lower()


def test_active_market_radar_keeps_qualified_setup_visible(monkeypatch):
    with TestClient(app):
        profile = instrument_registry.active
        candles = market_data_service.snapshot(limit=400)
        candidate = build_candidate_setup(candles, profile, None).model_copy(update={
            "direction": "LONG",
            "primary_entry_model": "Liquidity Sweep + Structure Shift",
            "primary_entry_model_key": "liquidity_sweep_structure_shift",
            "primary_model_score": 88.0,
            "confidence": 80.0,
            "confidence_grade": "A",
            "entry_valid": True,
            "model_selection_reason": "Qualified active-market candidate.",
        })

        async def fake_refresh(_symbol):
            return candles

        monkeypatch.setattr(market_data_service, "refresh_symbol_cache", fake_refresh)
        monkeypatch.setattr(radar_module, "build_candidate_setup", lambda *_args, **_kwargs: candidate)
        opportunity = asyncio.run(MultiMarketMonitorService()._scan_symbol(profile.symbol, datetime.now(timezone.utc)))

    assert opportunity.qualified is True
    assert opportunity.alertable is False
    assert opportunity.active_market is True
    assert opportunity.status == "SETUP_FORMING"
    assert opportunity.missing_gates == []
    assert opportunity.model_score == 88.0


def test_radar_exposes_missing_gates_instead_of_hiding_model(monkeypatch):
    with TestClient(app):
        profile = instrument_registry.active
        candles = market_data_service.snapshot(limit=400)
        candidate = build_candidate_setup(candles, profile, None).model_copy(update={
            "direction": "SHORT",
            "primary_entry_model": "OTE Retracement",
            "primary_entry_model_key": "ote_retracement",
            "primary_model_score": 60.0,
            "confidence": 40.0,
            "confidence_grade": "C",
            "entry_valid": False,
            "model_selection_reason": "Developing retracement candidate.",
        })

        async def fake_refresh(_symbol):
            return candles

        monkeypatch.setattr(market_data_service, "refresh_symbol_cache", fake_refresh)
        monkeypatch.setattr(radar_module, "build_candidate_setup", lambda *_args, **_kwargs: candidate)
        opportunity = asyncio.run(MultiMarketMonitorService()._scan_symbol(profile.symbol, datetime.now(timezone.utc)))

    assert opportunity.qualified is False
    assert opportunity.status == "DEVELOPING"
    assert "entry confirmation" in opportunity.missing_gates
    assert any(item.startswith("model score") for item in opportunity.missing_gates)
    assert any(item.startswith("confidence") for item in opportunity.missing_gates)
    assert opportunity.model == "OTE Retracement"


def test_frontend_has_desktop_claude_fallback_and_transparent_radar():
    for marker in [
        "fetchJsonWithTimeout",
        "/api/ai/analysis?force=${force",
        'source.addEventListener("heartbeat"',
        "Claude stream did not start",
        "runClaudeJsonFallback",
        "ACTIVE ENGINE",
        "missing_gates",
        "item.qualified",
    ]:
        assert marker in APP
    assert "3.1.8-claude-radar-resilience" in MAIN
    assert "tradeiq-v3.1.8-claude-radar-resilience-shell" in SW
