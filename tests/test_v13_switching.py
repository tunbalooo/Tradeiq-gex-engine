import asyncio
from pathlib import Path

from backend.services.claude_analysis import SYSTEM_PROMPT
from backend.services.market_data import DatabentoMarketDataService

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")


def test_databento_symbol_switch_returns_preview_without_waiting_for_history(monkeypatch):
    service = DatabentoMarketDataService(max_candles=2400)
    monkeypatch.setattr(service, "_schedule_history_refresh", lambda profile, generation=None: None)
    result = asyncio.run(service.switch_symbol("ES"))
    assert result["symbol"] == "ES"
    assert result["warming"] is True
    assert result["candle_count"] > 1000


def test_frontend_defers_automatic_claude_until_history_is_ready():
    assert "marketWarming" in APP
    assert "DATABENTO SYNC" in APP
    assert "if (!force && state.marketWarming) return;" in APP
    assert "async function reloadSyncedHistory" in APP
    assert "await reloadSyncedHistory();" in APP


def test_claude_prompt_does_not_turn_fallback_gex_into_execution_gate():
    prompt = SYSTEM_PROMPT.lower()
    assert "fallback or simulated gex is a reliability limitation only" in prompt
    assert "does not independently block order arming" in prompt
    assert "never say an order must wait for gex" in prompt


def test_trade_engine_source_contains_data_readiness_gate():
    source = (ROOT / "backend" / "services" / "trade_engine.py").read_text(encoding="utf-8")
    assert 'market.get("warming")' in source
    assert 'not market.get("history_cached", False)' in source
    assert '"status": "DATA_SYNCING"' in source
    assert 'self._current.order_state == "PREVIEW_ONLY"' in source
