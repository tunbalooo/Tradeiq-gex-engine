"""
Live market data service — replaces SimulatedMarketDataService when
SIMULATED_MODE=false.

Data source: yfinance (free, ~15min delayed on the free tier). This is the
"prove it works" data source. Swap this class for an Interactive Brokers or
Databento adapter later without touching setup_service.py, routes.py, or the
frontend — they only depend on the public interface below:

    .symbol / .current_price / .candles
    .next_candle()  .snapshot(limit)  .price_change()  .overview()

Design notes:
- yfinance is rate-limit-sensitive, and the app calls next_candle() every
  UPDATE_INTERVAL_SECONDS (default 2s). We do NOT hit the network that often.
  A full history/refresh happens every `refresh_seconds` (default 30s); in
  between ticks we keep serving the last known candle so the websocket loop
  never breaks, and we just nudge the close with the freshest fast_info price
  when available (near-zero-cost call).
- If yfinance/network fails (common in sandboxed or offline environments),
  we log a warning and fall back to holding the last good candle rather than
  crashing the app.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from backend.core.config import settings
from backend.models.schemas import Candle, MarketOverviewItem

logger = logging.getLogger("tradeiq.live_market_data")

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - dependency documented in requirements.txt
    yf = None


OVERVIEW_TICKERS = {
    "ES1!": "ES=F",
    "YM1!": "YM=F",
    "RTY1!": "RTY=F",
    "VIX": "^VIX",
}


class LiveMarketDataService:
    """Real NQ/MNQ candles + overview, refreshed on a background timer."""

    def __init__(self, max_candles: int = 2400):
        if yf is None:
            raise RuntimeError(
                "yfinance is not installed. Run `pip install -r requirements.txt` "
                "or set SIMULATED_MODE=true to run without live data."
            )

        self.symbol = settings.live_price_symbol  # e.g. "MNQ=F"
        self.candles: deque[Candle] = deque(maxlen=max_candles)
        self.current_price: float = settings.simulation_start_price
        self.session_reference: float = settings.simulation_start_price
        self._overview_cache: list[MarketOverviewItem] = []
        self._lock = threading.Lock()
        self._refresh_seconds = max(10, settings.live_refresh_seconds)
        self._last_refresh = 0.0

        self._full_refresh()  # populate synchronously so the app has data on boot

    # ── data fetch ──────────────────────────────────────────────────
    def _fetch_history(self) -> list[Candle]:
        ticker = yf.Ticker(self.symbol)
        bars = ticker.history(period="5d", interval="1m")
        if bars is None or bars.empty:
            raise RuntimeError(f"No candles returned for {self.symbol}")

        out: list[Candle] = []
        for ts, row in bars.iterrows():
            out.append(
                Candle(
                    time=ts.to_pydatetime().astimezone(timezone.utc),
                    open=round(float(row["Open"]), 2),
                    high=round(float(row["High"]), 2),
                    low=round(float(row["Low"]), 2),
                    close=round(float(row["Close"]), 2),
                    volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                )
            )
        return out

    def _fetch_overview(self) -> list[MarketOverviewItem]:
        items: list[MarketOverviewItem] = []
        nq_change, nq_percent = self.price_change()
        items.append(
            MarketOverviewItem(
                symbol="NQ1!", price=self.current_price,
                change=round(nq_change, 2), change_percent=round(nq_percent, 2),
            )
        )
        for label, yf_symbol in OVERVIEW_TICKERS.items():
            try:
                t = yf.Ticker(yf_symbol)
                fast = t.fast_info
                price = float(fast["last_price"])
                prev = float(fast["previous_close"]) or price
                change = price - prev
                percent = (change / prev * 100) if prev else 0.0
                items.append(
                    MarketOverviewItem(
                        symbol=label, price=round(price, 2),
                        change=round(change, 2), change_percent=round(percent, 2),
                    )
                )
            except Exception as exc:  # keep going even if one ticker fails
                logger.warning("overview fetch failed for %s: %s", yf_symbol, exc)
        return items

    def _full_refresh(self) -> None:
        try:
            history = self._fetch_history()
        except Exception as exc:
            logger.warning("live history refresh failed for %s: %s", self.symbol, exc)
            if not self.candles:
                # No data at all yet (e.g. first boot with no network) —
                # seed one placeholder candle so the app doesn't crash.
                now = datetime.now(timezone.utc)
                self.candles.append(
                    Candle(time=now, open=self.current_price, high=self.current_price,
                           low=self.current_price, close=self.current_price, volume=0)
                )
            self._last_refresh = time.time()
            return

        with self._lock:
            self.candles.clear()
            self.candles.extend(history)
            self.current_price = self.candles[-1].close
            self.session_reference = (
                self.candles[-390].close if len(self.candles) >= 390 else self.candles[0].close
            )
        try:
            self._overview_cache = self._fetch_overview()
        except Exception as exc:
            logger.warning("overview refresh failed: %s", exc)
        self._last_refresh = time.time()

    def _maybe_refresh(self) -> None:
        if time.time() - self._last_refresh >= self._refresh_seconds:
            self._full_refresh()

    def _nudge_last_price(self) -> None:
        """Cheap live-feel update between full refreshes: pull just the latest price."""
        if yf is None or not self.candles:
            return
        try:
            fast = yf.Ticker(self.symbol).fast_info
            price = float(fast["last_price"])
        except Exception:
            return
        with self._lock:
            last = self.candles[-1]
            updated = Candle(
                time=last.time,
                open=last.open,
                high=max(last.high, price),
                low=min(last.low, price),
                close=round(price, 2),
                volume=last.volume,
            )
            self.candles[-1] = updated
            self.current_price = updated.close

    # ── public interface (mirrors SimulatedMarketDataService) ────────
    def next_candle(self) -> Candle:
        self._maybe_refresh()
        if not self.candles:
            self._nudge_last_price()
        else:
            # Between full history refreshes, keep the tape moving with the
            # freshest quote rather than fabricating a new bar.
            self._nudge_last_price()
        return self.candles[-1]

    def snapshot(self, limit: int | None = None) -> list[Candle]:
        values = list(self.candles)
        return values[-limit:] if limit else values

    def price_change(self) -> tuple[float, float]:
        change = self.current_price - self.session_reference
        percent = (change / self.session_reference * 100) if self.session_reference else 0.0
        return change, percent

    def overview(self) -> list[MarketOverviewItem]:
        return self._overview_cache or [
            MarketOverviewItem(symbol="NQ1!", price=self.current_price, change=0.0, change_percent=0.0)
        ]
