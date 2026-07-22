from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.services.instruments import get_instrument
from backend.services.market_data import DatabentoMarketDataService, SimulatedMarketDataService

ROOT = Path(__file__).resolve().parents[1]
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


class FakeOhlcvRecord:
    def __init__(self, timestamp: datetime, price: float = 30000.0, volume: int = 10):
        self.ts_event = int(timestamp.timestamp() * 1_000_000_000)
        self.open = int(price * 1_000_000_000)
        self.high = int((price + 1.0) * 1_000_000_000)
        self.low = int((price - 1.0) * 1_000_000_000)
        self.close = int((price + 0.25) * 1_000_000_000)
        self.pretty_open = price
        self.pretty_high = price + 1.0
        self.pretty_low = price - 1.0
        self.pretty_close = price + 0.25
        self.volume = volume


def test_frontend_regime_filter_is_session_break_aware():
    assert "SESSION_BREAK_MULTIPLIER = 3" in CHART
    assert "MIN_SESSION_BREAK_MS = 60 * 60 * 1000" in CHART
    assert "function medianSpacing" in CHART
    assert "if (sessionBreak) continue" in CHART
    # The original protection remains present for contiguous corrupt regimes.
    assert "MAX_SERIES_REGIME_GAP = 0.08" in CHART
    assert "if (Math.abs(current - previous) / previous > maxGap) start = index" in CHART


def test_simulated_health_never_claims_live_fresh_market_data():
    health = SimulatedMarketDataService(max_candles=50).health()
    assert health["mode"] == "simulated"
    assert health["stream_state"] == "SIMULATED"
    assert health["data_fresh"] is False
    assert health["data_quality"] == "SIMULATED"


def test_databento_live_overlay_is_bounded_to_max_candles():
    service = DatabentoMarketDataService(max_candles=3)
    profile = get_instrument("NQ")
    service.instrument = profile
    service._generation = 7
    start = datetime(2026, 7, 20, 13, 30, tzinfo=timezone.utc)

    for offset in range(7):
        service._on_record(FakeOhlcvRecord(start + timedelta(minutes=offset), 30000 + offset), profile, 7)

    assert len(service._live_overlay) == 3
    assert sorted(service._live_overlay) == [
        start + timedelta(minutes=4),
        start + timedelta(minutes=5),
        start + timedelta(minutes=6),
    ]


def test_v309_version_and_shell_cache_are_bumped():
    assert "3.0.9-chart-pipeline-integrity" in MAIN
    assert 'tradeiq-v3.0.9-chart-pipeline-integrity-shell' in SW
