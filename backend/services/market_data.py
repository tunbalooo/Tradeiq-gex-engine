import asyncio
import logging
import random
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from math import sin
from typing import Any

from backend.core.config import settings
from backend.models.schemas import Candle, MarketOverviewItem

logger = logging.getLogger(__name__)

NANO = 1_000_000_000


def _pretty_price(record: Any, field: str) -> float:
    pretty_name = f"pretty_{field}"
    value = getattr(record, pretty_name, None)
    if value is not None:
        return float(value)
    raw = getattr(record, field)
    return float(raw) / NANO


def _record_time(record: Any) -> datetime:
    ns = int(getattr(record, "ts_event"))
    return datetime.fromtimestamp(ns / NANO, tz=timezone.utc)


class SimulatedMarketDataService:
    mode = "simulated"
    data_source = "local-generator"
    connected = True
    last_error: str | None = None

    def __init__(self, max_candles: int = 2400):
        self.symbol = settings.simulation_symbol
        self.current_price = settings.simulation_start_price
        self.candles: deque[Candle] = deque(maxlen=max_candles)
        self._rng = random.Random(57255)
        self._seed_history()
        self.session_reference = self.candles[-390].close if len(self.candles) >= 390 else self.candles[0].close

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

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

    def latest_candle(self) -> Candle:
        return self.next_candle()

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

    def health(self) -> dict:
        return {
            "mode": self.mode,
            "data_source": self.data_source,
            "connected": self.connected,
            "last_error": self.last_error,
            "symbol": self.symbol,
            "candle_count": len(self.candles),
        }


class DatabentoMarketDataService:
    mode = "live"
    data_source = "databento"
    symbol = "NQ"

    def __init__(self, max_candles: int = 2400):
        self.candles: deque[Candle] = deque(maxlen=max_candles)
        self.current_price = settings.simulation_start_price
        self.session_reference = self.current_price
        self.connected = False
        self.last_error: str | None = None
        self.raw_symbol: str | None = None
        self._live_client = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            await asyncio.to_thread(self._seed_history)
            self._thread = threading.Thread(target=self._run_live, name="databento-nq-live", daemon=True)
            self._thread.start()
        except Exception as exc:
            self.last_error = str(exc)
            self.connected = False
            logger.exception("Unable to start Databento market data")
            if not self.candles:
                self._seed_local_fallback()

    async def stop(self) -> None:
        client = self._live_client
        if client is not None:
            try:
                client.stop()
            except Exception:
                logger.debug("Databento live stop failed", exc_info=True)
        self.connected = False

    def _import_db(self):
        try:
            import databento as db
        except ImportError as exc:
            raise RuntimeError(
                "The databento package is not installed. Run: python -m pip install -U databento"
            ) from exc
        return db

    def _seed_history(self) -> None:
        db = self._import_db()
        client = db.Historical(key=settings.databento_api_key)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(settings.databento_history_days, 2))

        store = client.timeseries.get_range(
            dataset=settings.databento_dataset,
            schema="ohlcv-1m",
            stype_in="continuous",
            symbols=[settings.databento_futures_symbol],
            start=start.isoformat(),
            end=end.isoformat(),
        )

        loaded: list[Candle] = []
        for record in store:
            if not all(hasattr(record, field) for field in ("open", "high", "low", "close", "volume")):
                continue
            loaded.append(
                Candle(
                    time=_record_time(record),
                    open=round(_pretty_price(record, "open"), 2),
                    high=round(_pretty_price(record, "high"), 2),
                    low=round(_pretty_price(record, "low"), 2),
                    close=round(_pretty_price(record, "close"), 2),
                    volume=int(record.volume),
                )
            )

        loaded.sort(key=lambda candle: candle.time)
        with self._lock:
            self.candles.clear()
            for candle in loaded[-settings.databento_history_limit:]:
                self.candles.append(candle)
            if self.candles:
                self.current_price = self.candles[-1].close
                self.session_reference = (
                    self.candles[-390].close if len(self.candles) >= 390 else self.candles[0].close
                )
        if not loaded:
            raise RuntimeError("Databento returned no NQ historical bars for the configured symbol.")

    def _seed_local_fallback(self) -> None:
        fallback = SimulatedMarketDataService()
        with self._lock:
            self.candles.clear()
            self.candles.extend(fallback.snapshot())
            self.current_price = fallback.current_price
            self.session_reference = fallback.session_reference

    def _run_live(self) -> None:
        try:
            db = self._import_db()
            client = db.Live(
                key=settings.databento_api_key,
                reconnect_policy="reconnect",
            )
            self._live_client = client
            client.subscribe(
                dataset=settings.databento_dataset,
                schema="ohlcv-1s",
                stype_in="continuous",
                symbols=[settings.databento_futures_symbol],
            )
            client.add_callback(self._on_record, self._on_callback_error)
            self.connected = True
            client.start()
            client.block_for_close()
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            logger.exception("Databento live NQ stream stopped")

    def _on_callback_error(self, exc: Exception) -> None:
        self.last_error = str(exc)
        logger.error("Databento callback error: %s", exc)

    def _on_record(self, record: Any) -> None:
        if hasattr(record, "stype_out_symbol"):
            self.raw_symbol = str(record.stype_out_symbol)
            return
        if not all(hasattr(record, field) for field in ("open", "high", "low", "close", "volume")):
            return

        event_time = _record_time(record)
        minute = event_time.replace(second=0, microsecond=0)
        open_px = _pretty_price(record, "open")
        high_px = _pretty_price(record, "high")
        low_px = _pretty_price(record, "low")
        close_px = _pretty_price(record, "close")
        volume = int(record.volume)

        with self._lock:
            if self.candles and self.candles[-1].time == minute:
                last = self.candles[-1]
                self.candles[-1] = Candle(
                    time=minute,
                    open=last.open,
                    high=round(max(last.high, high_px), 2),
                    low=round(min(last.low, low_px), 2),
                    close=round(close_px, 2),
                    volume=last.volume + volume,
                )
            else:
                self.candles.append(
                    Candle(
                        time=minute,
                        open=round(open_px, 2),
                        high=round(high_px, 2),
                        low=round(low_px, 2),
                        close=round(close_px, 2),
                        volume=volume,
                    )
                )
            self.current_price = round(close_px, 2)
            self.connected = True
            self.last_error = None

    def latest_candle(self) -> Candle:
        with self._lock:
            if not self.candles:
                raise RuntimeError("No NQ candles are available.")
            return self.candles[-1].model_copy(deep=True)

    def snapshot(self, limit: int | None = None) -> list[Candle]:
        with self._lock:
            values = [candle.model_copy(deep=True) for candle in self.candles]
        return values[-limit:] if limit else values

    def price_change(self) -> tuple[float, float]:
        change = self.current_price - self.session_reference
        percent = (change / self.session_reference * 100) if self.session_reference else 0.0
        return change, percent

    def overview(self) -> list[MarketOverviewItem]:
        change, percent = self.price_change()
        return [
            MarketOverviewItem(symbol="NQ1!", price=round(self.current_price, 2), change=round(change, 2), change_percent=round(percent, 2)),
        ]

    def health(self) -> dict:
        return {
            "mode": self.mode,
            "data_source": self.data_source,
            "connected": self.connected,
            "last_error": self.last_error,
            "symbol": settings.databento_futures_symbol,
            "raw_symbol": self.raw_symbol,
            "candle_count": len(self.candles),
        }


market_data_service = (
    DatabentoMarketDataService()
    if settings.use_databento
    else SimulatedMarketDataService()
)
