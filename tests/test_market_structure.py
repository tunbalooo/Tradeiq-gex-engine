from datetime import datetime, timedelta, timezone

from backend.models.schemas import Candle
from engine.market_structure import analyze_market_structure


def test_directional_sell_side_sweep_is_identified():
    now = datetime.now(timezone.utc)
    candles = []
    price = 100.0
    for i in range(65):
        close = price + 0.3
        candles.append(Candle(time=now + timedelta(minutes=5*i), open=price, high=close+0.2, low=price-0.2, close=close, volume=100))
        price = close
    prior_low = min(c.low for c in candles[-15:])
    candles.append(Candle(time=now + timedelta(minutes=5*65), open=price, high=price+1, low=prior_low-1, close=prior_low+0.5, volume=500))
    result = analyze_market_structure(candles)
    assert result["sell_side_sweep"] is True
    assert result["buy_side_sweep"] is False
