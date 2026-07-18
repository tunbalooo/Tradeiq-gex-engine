import asyncio
import random
from math import sin
from collections import deque
from datetime import datetime, timedelta, timezone

from backend.core.config import settings
from backend.models.schemas import Candle, MarketOverviewItem


class SimulatedMarketDataService:
    """Deterministic accelerated one-minute NQ market used by the local prototype."""

    def __init__(self, max_candles: int = 2400):
        self.symbol = settings.simulation_symbol
        self.current_price = settings.simulation_start_price
        self.candles: deque[Candle] = deque(maxlen=max_candles)
        self._rng = random.Random(57255)
        self._seed_history()
        self.session_reference = self.candles[-390].close if len(self.candles) >= 390 else self.candles[0].close

    def _seed_history(self) -> None:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        count = 1920
        price = self.current_price - 115

        for index in range(count):
            timestamp = now - timedelta(minutes=count - index)
            progress = index / max(1, count - 1)
            target_path = (
                settings.simulation_start_price - 115
                + progress * 115
                + 24 * sin(index / 73)
                + 11 * sin(index / 19)
            )
            open_price = price
            move = (target_path - open_price) * 0.12 + self._rng.gauss(0, 1.95)
            close = open_price + move
            high = max(open_price, close) + abs(self._rng.gauss(0.85, 0.55))
            low = min(open_price, close) - abs(self._rng.gauss(0.85, 0.55))
            volume = self._rng.randint(110, 780)

            self.candles.append(
                Candle(
                    time=timestamp,
                    open=round(open_price, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    close=round(close, 2),
                    volume=volume,
                )
            )
            price = close

        self.current_price = self.candles[-1].close

    def next_candle(self) -> Candle:
        last = self.candles[-1]
        timestamp = last.time + timedelta(minutes=1)
        open_price = last.close
        recent_direction = self.candles[-1].close - self.candles[-20].close
        drift = 0.10 if recent_direction >= 0 else -0.06
        move = drift + self._rng.gauss(0, 2.1)
        close = open_price + move
        high = max(open_price, close) + abs(self._rng.gauss(0.75, 0.45))
        low = min(open_price, close) - abs(self._rng.gauss(0.75, 0.45))

        candle = Candle(
            time=timestamp,
            open=round(open_price, 2),
            high=round(high, 2),
            low=round(low, 2),
            close=round(close, 2),
            volume=self._rng.randint(120, 820),
        )
        self.candles.append(candle)
        self.current_price = candle.close
        return candle

    async def stream(self):
        while True:
            yield self.next_candle()
            await asyncio.sleep(settings.update_interval_seconds)

    def snapshot(self, limit: int | None = None) -> list[Candle]:
        values = list(self.candles)
        return values[-limit:] if limit else values

    def price_change(self) -> tuple[float, float]:
        change = self.current_price - self.session_reference
        percent = (change / self.session_reference * 100) if self.session_reference else 0.0
        return change, percent

    def overview(self) -> list[MarketOverviewItem]:
        nq_change, nq_percent = self.price_change()
        nq_ratio = self.current_price / settings.simulation_start_price
        synthetic = [
            ("NQ1!", self.current_price, nq_change, nq_percent),
            ("ES1!", 5521.00 * (0.999 + (nq_ratio - 1) * 0.68), nq_change * 0.17, nq_percent * 0.72),
            ("YM1!", 39850.0 * (0.9995 + (nq_ratio - 1) * 0.42), nq_change * 0.82, nq_percent * 0.48),
            ("RTY1!", 2083.40 * (0.999 + (nq_ratio - 1) * 0.86), nq_change * 0.07, nq_percent * 0.91),
            ("VIX", max(9.5, 12.45 - nq_percent * 1.65), -nq_percent * 0.22, -nq_percent * 1.28),
        ]
        return [
            MarketOverviewItem(
                symbol=symbol,
                price=round(price, 2),
                change=round(change, 2),
                change_percent=round(percent, 2),
            )
            for symbol, price, change, percent in synthetic
        ]


def _build_market_data_service():
    if settings.simulated_mode:
        return SimulatedMarketDataService()

    provider = (settings.data_provider or "yfinance").lower()
    if provider == "databento":
        try:
            from backend.services.databento_market_data import DatabentoMarketDataService

            return DatabentoMarketDataService()
        except Exception as exc:  # pragma: no cover
            import logging
            logging.getLogger("tradeiq.market_data").error(
                "Databento market data failed to start (%s). Falling back to yfinance. "
                "Check DATABENTO_API_KEY, live CME entitlement, and that databento is installed.",
                exc,
            )
    try:
        from backend.services.live_market_data import LiveMarketDataService

        return LiveMarketDataService()
    except Exception as exc:  # pragma: no cover
        import logging
        logging.getLogger("tradeiq.market_data").error(
            "Live market data failed (%s); using simulated.", exc,
        )
        return SimulatedMarketDataService()


market_data_service = _build_market_data_service()
