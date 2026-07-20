from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.models.schemas import Candle
from backend.services.market_data import _plausible_live_ohlc, _sanitize_candles
from backend.services.timeframes import aggregate_candles

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _candle(time: datetime, open_: float, high: float, low: float, close: float, volume: int = 100) -> Candle:
    return Candle(time=time, open=open_, high=high, low=low, close=close, volume=volume)


def test_aggregate_candles_orders_and_deduplicates_small_timeframe_data():
    start = datetime(2026, 7, 20, 13, 30, tzinfo=timezone.utc)
    candles = [
        _candle(start + timedelta(minutes=1), 101, 103, 100, 102),
        _candle(start, 100, 102, 99, 101),
        _candle(start + timedelta(minutes=1), 101, 104, 100, 103, 150),
    ]

    one_minute = aggregate_candles(candles, 1)
    assert [item.time for item in one_minute] == [start, start + timedelta(minutes=1)]
    assert one_minute[-1].high == 104
    assert one_minute[-1].close == 103


def test_market_sanitizer_removes_isolated_giant_wick():
    start = datetime(2026, 7, 20, 13, 30, tzinfo=timezone.utc)
    candles = []
    price = 30000.0
    for index in range(35):
        candles.append(_candle(start + timedelta(minutes=index), price, price + 12, price - 10, price + 2))
        price += 2
    spike_time = start + timedelta(minutes=35)
    candles.append(_candle(spike_time, price, price + 900, price - 8, price + 3))
    candles.append(_candle(spike_time + timedelta(minutes=1), price + 3, price + 15, price - 5, price + 5))

    clean = _sanitize_candles(candles)
    assert spike_time not in {item.time for item in clean}


def test_live_guard_rejects_corrupt_one_second_ohlc():
    assert _plausible_live_ohlc(30000, 30020, 29990, 30010, 30000, 0.25)
    assert not _plausible_live_ohlc(30000, 30900, 29990, 30010, 30000, 0.25)
    assert not _plausible_live_ohlc(30000, 29990, 30010, 30005, 30000, 0.25)


def test_frontend_uses_price_first_autoscale_and_viewport_memory():
    assert "autoscaleInfoProvider" in CHART
    assert 'TradingView\'s "scale price chart only" behaviour' in CHART
    assert "desktopViewportCache" in CHART
    assert "normaliseMarketCandles" in APP
    assert "upsertBaseCandle" in APP
    assert "3.0.1-chart-candle-hotfix" in MAIN
    assert 'CACHE_NAME = "tradeiq-v3.0.1-chart-hotfix-shell"' in SW
