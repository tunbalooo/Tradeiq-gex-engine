"""
Databento market data — native CME NQ futures candles via GLBX.MDP3.

Same public interface as SimulatedMarketDataService / LiveMarketDataService
(symbol / current_price / candles / next_candle / snapshot / price_change /
overview) so it drops into market_data.py behind DATA_PROVIDER=databento.

Design:
- Historical backfill on boot via the Databento *historical* client
  (ohlcv-1m for the last few sessions) so the chart has depth immediately.
- A background *live* subscription (ohlcv-1s on NQ.v.0) keeps a rolling
  latest price; we fold 1s bars into the current 1-minute candle.
- If anything fails (no live entitlement, market closed, network), we hold
  the last good candle instead of crashing — the app stays up.

NOTE: Databento live data is licensed for personal use on your local machine.
Run this provider locally; keep Railway on yfinance.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timedelta, timezone

from backend.core.config import settings
from backend.models.schemas import Candle, MarketOverviewItem

logger = logging.getLogger("tradeiq.databento_market_data")

try:
    import databento as db
except ImportError:  # pragma: no cover
    db = None

# NQ = $20/point; used only for the overview % (price comes straight from feed).
_SCALE = 1e-9  # Databento prices are fixed-point (1e-9); divide to get real px


def _px(fixed_price: int) -> float:
    return round(fixed_price * _SCALE, 2)


class DatabentoMarketDataService:
    def __init__(self, max_candles: int = 2400):
        if db is None:
            raise RuntimeError("databento not installed. pip install databento")
        if not settings.databento_api_key:
            raise RuntimeError("DATABENTO_API_KEY is not set")

        self.symbol = settings.databento_price_symbol  # NQ.v.0
        self.candles: deque[Candle] = deque(maxlen=max_candles)
        self.current_price: float = settings.simulation_start_price
        self.session_reference: float = settings.simulation_start_price
        self._lock = threading.Lock()
        self._live = None

        self._backfill()
        self._start_live()

    # ── historical backfill ─────────────────────────────────────────
    def _backfill(self) -> None:
        try:
            client = db.Historical(settings.databento_api_key)
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=3)
            data = client.timeseries.get_range(
                dataset=settings.databento_dataset,
                schema="ohlcv-1m",
                stype_in="continuous",
                symbols=[self.symbol],
                start=start,
                end=end,
            )
            df = data.to_df()
            bars: list[Candle] = []
            for ts, row in df.iterrows():
                bars.append(Candle(
                    time=ts.to_pydatetime().astimezone(timezone.utc),
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    volume=int(row.get("volume", 0) or 0),
                ))
            if bars:
                with self._lock:
                    self.candles.extend(bars[-2400:])
                    self.current_price = self.candles[-1].close
                    self.session_reference = (
                        self.candles[-390].close if len(self.candles) >= 390 else self.candles[0].close
                    )
                logger.info("Databento backfill: %d NQ 1m candles", len(bars))
        except Exception as exc:
            logger.warning("Databento backfill failed: %s", exc)
            if not self.candles:
                now = datetime.now(timezone.utc)
                self.candles.append(Candle(time=now, open=self.current_price, high=self.current_price,
                                           low=self.current_price, close=self.current_price, volume=0))

    # ── live subscription ───────────────────────────────────────────
    def _start_live(self) -> None:
        try:
            self._live = db.Live(key=settings.databento_api_key)
            self._live.subscribe(
                dataset=settings.databento_dataset,
                schema="ohlcv-1s",
                stype_in="continuous",
                symbols=[self.symbol],
            )
            self._live.add_callback(self._on_record)
            self._live.start()
            logger.info("Databento live NQ subscription started")
        except Exception as exc:
            logger.warning("Databento live start failed (using backfill only): %s", exc)

    def _on_record(self, record) -> None:
        # Only OHLCV bars carry price; ignore symbol-mapping/system messages.
        o = getattr(record, "open", None)
        if o is None:
            return
        try:
            close = _px(record.close)
            ts = datetime.fromtimestamp(record.ts_event / 1e9, tz=timezone.utc)
        except Exception:
            return
        minute = ts.replace(second=0, microsecond=0)
        with self._lock:
            self.current_price = close
            last = self.candles[-1] if self.candles else None
            if last and last.time == minute:
                self.candles[-1] = Candle(
                    time=minute, open=last.open,
                    high=max(last.high, _px(record.high)),
                    low=min(last.low, _px(record.low)),
                    close=close, volume=last.volume + int(getattr(record, "volume", 0) or 0),
                )
            else:
                self.candles.append(Candle(
                    time=minute, open=_px(record.open), high=_px(record.high),
                    low=_px(record.low), close=close, volume=int(getattr(record, "volume", 0) or 0),
                ))

    # ── public interface ────────────────────────────────────────────
    def next_candle(self) -> Candle:
        with self._lock:
            return self.candles[-1]

    def snapshot(self, limit: int | None = None) -> list[Candle]:
        with self._lock:
            values = list(self.candles)
        return values[-limit:] if limit else values

    def price_change(self) -> tuple[float, float]:
        change = self.current_price - self.session_reference
        percent = (change / self.session_reference * 100) if self.session_reference else 0.0
        return change, percent

    def overview(self) -> list[MarketOverviewItem]:
        change, percent = self.price_change()
        return [MarketOverviewItem(symbol="NQ1!", price=self.current_price,
                                   change=round(change, 2), change_percent=round(percent, 2))]
