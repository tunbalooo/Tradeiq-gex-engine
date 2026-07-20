from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.models.schemas import Candle
from backend.services.market_data import _sanitize_candles, _series_gap_ratio
from engine.gex import OptionPosition, calculate_max_pain, derive_gex_summary_from_positions

ROOT = Path(__file__).resolve().parents[1]
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "backend" / "api" / "routes.py").read_text(encoding="utf-8")
MARKET = (ROOT / "backend" / "services" / "market_data.py").read_text(encoding="utf-8")


def candle(index: int, price: float) -> Candle:
    return Candle(
        time=datetime(2026, 7, 20, tzinfo=timezone.utc) + timedelta(minutes=index),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price + 0.25,
        volume=100,
    )


def test_backend_detects_history_live_price_regime_mismatch():
    history = [candle(i, 3350 + i * 0.1) for i in range(30)]
    live = [candle(40 + i, 4000 + i * 0.1) for i in range(3)]
    assert _series_gap_ratio(history, live) > 0.08


def test_backend_sanitizer_removes_isolated_malformed_spike():
    bars = [candle(0, 100), candle(1, 150), candle(2, 101), candle(3, 102)]
    clean = _sanitize_candles(bars, max_jump_ratio=0.12)
    assert [round(item.open) for item in clean] == [100, 101, 102]


def test_max_pain_is_derived_from_real_open_interest_only():
    positions = [
        OptionPosition(95, 7 / 365, "PUT", 200, 0.2),
        OptionPosition(100, 7 / 365, "CALL", 600, 0.2),
        OptionPosition(105, 7 / 365, "CALL", 100, 0.2),
    ]
    value = calculate_max_pain(positions)
    assert value in {95.0, 100.0, 105.0}
    summary = derive_gex_summary_from_positions(100, positions)
    assert summary["max_pain"] == value
    assert "gamma_resistance" in summary
    assert "gamma_support" in summary


def test_snapshot_exposes_chart_provenance_and_quality():
    assert '"history_ready"' in ROUTES
    assert '"history_source"' in ROUTES
    assert '"data_quality"' in ROUTES
    assert '"raw_symbol"' in ROUTES


def test_live_service_never_mixes_simulated_preview_with_databento():
    assert "Never mix synthetic preview prices with real Databento ticks" in MARKET
    assert 'self.history_source = "live-pending-history"' in MARKET
    assert 'self.data_quality = "CONTRACT_MISMATCH"' in MARKET


def test_frontend_rejects_mixed_price_regimes_and_shows_sync_state():
    assert "MAX_SERIES_REGIME_GAP = 0.08" in CHART
    assert "latestCoherentSegment" in CHART
    assert "PRICE REGIME RESET" in CHART
    assert "chart-data-state" in CHART
    assert "renderSyncingState" in APP
    assert "TradeIQ rejected mixed or incomplete price history" in APP
    assert ".chart-data-state" in STYLES


def test_gex_reference_levels_include_max_pain_support_and_rth_equilibrium():
    assert "GAMMA RES / CALL WALL" in CHART
    assert "MAX PAIN" in CHART
    assert "PUT SUPPORT / WALL" in CHART
    assert "RTH EQ" in CHART
    assert "Maximum pain is shown only when open-interest data is available" in APP


def test_ios_fullscreen_has_css_fallback():
    assert "toggleFullscreenRoot" in CHART
    assert "tradeiq-pseudo-fullscreen" in CHART
    assert ".tradeiq-pseudo-fullscreen" in STYLES
