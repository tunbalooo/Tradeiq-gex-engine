import asyncio
import logging
import random
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from math import sin
from typing import Any
from zoneinfo import ZoneInfo

from backend.core.config import settings
from backend.models.schemas import Candle, MarketOverviewItem

logger = logging.getLogger(__name__)
NANO = 1_000_000_000


def _pretty_price(record: Any, field: str) -> float:
    value = getattr(record, f"pretty_{field}", None)
    if value is not None:
        return float(value)
    return float(getattr(record, field)) / NANO


def _record_time(record: Any) -> datetime:
    return datetime.fromtimestamp(int(getattr(record, "ts_event")) / NANO, tz=timezone.utc)


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def available_dataset_end(client: Any, dataset: str, schema: str, requested: datetime) -> datetime:
    """Clamp a historical request to the most recent timestamp available from Databento."""
    requested = requested if requested.tzinfo else requested.replace(tzinfo=timezone.utc)
    try:
        info = client.metadata.get_dataset_range(dataset=dataset)
        if hasattr(info, "to_dict"):
            info = info.to_dict()
        if not isinstance(info, dict):
            info = vars(info)
        schema_info = (info.get("schema") or {}).get(schema) or {}
        raw_end = schema_info.get("end") or info.get("end")
        if raw_end:
            return min(requested, _as_datetime(raw_end))
    except Exception:
        logger.debug("Unable to read Databento dataset range; using conservative end", exc_info=True)
    return min(requested, datetime.now(timezone.utc) - timedelta(minutes=15))


def rth_candles(candles: list[Candle], now: datetime | None = None) -> list[Candle]:
    if not candles:
        return []
    tz = ZoneInfo(settings.rth_timezone)
    local_now = (now or candles[-1].time).astimezone(tz)
    session_date = local_now.date()
    start_local = datetime(
        session_date.year, session_date.month, session_date.day,
        settings.rth_start_hour, settings.rth_start_minute, tzinfo=tz,
    )
    end_local = datetime(
        session_date.year, session_date.month, session_date.day,
        settings.rth_end_hour, settings.rth_end_minute, tzinfo=tz,
    )
    start_utc, end_utc = start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
    values = [c for c in candles if start_utc <= c.time < end_utc]
    if values:
        return values
    # Before RTH opens, use the previous trading day's RTH data.
    for offset in range(1, 5):
        prior = session_date - timedelta(days=offset)
        if prior.weekday() >= 5:
            continue
        pstart = datetime(prior.year, prior.month, prior.day, settings.rth_start_hour, settings.rth_start_minute, tzinfo=tz).astimezone(timezone.utc)
        pend = datetime(prior.year, prior.month, prior.day, settings.rth_end_hour, settings.rth_end_minute, tzinfo=tz).astimezone(timezone.utc)
        values = [c for c in candles if pstart <= c.time < pend]
        if values:
            return values
    return candles[-390:]


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
        self._task: asyncio.Task | None = None
        self._seed_history()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="simulated-market-data")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(max(1, settings.update_interval_seconds))
            self._append_candle()

    def _seed_history(self) -> None:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        count = 1920
        price = self.current_price - 115
        for index in range(count):
            timestamp = now - timedelta(minutes=count - index)
            progress = index / max(1, count - 1)
            target = settings.simulation_start_price - 115 + progress * 115 + 24 * sin(index / 73) + 11 * sin(index / 19)
            open_price = price
            close = open_price + (target - open_price) * 0.12 + self._rng.gauss(0, 1.95)
            high = max(open_price, close) + abs(self._rng.gauss(0.85, 0.55))
            low = min(open_price, close) - abs(self._rng.gauss(0.85, 0.55))
            self.candles.append(Candle(time=timestamp, open=round(open_price, 2), high=round(high, 2), low=round(low, 2), close=round(close, 2), volume=self._rng.randint(110, 780)))
            price = close
        self.current_price = self.candles[-1].close

    def _append_candle(self) -> Candle:
        last = self.candles[-1]
        open_price = last.close
        recent_direction = last.close - self.candles[-20].close
        close = open_price + (0.10 if recent_direction >= 0 else -0.06) + self._rng.gauss(0, 2.1)
        candle = Candle(
            time=last.time + timedelta(minutes=1),
            open=round(open_price, 2),
            high=round(max(open_price, close) + abs(self._rng.gauss(0.75, 0.45)), 2),
            low=round(min(open_price, close) - abs(self._rng.gauss(0.75, 0.45)), 2),
            close=round(close, 2), volume=self._rng.randint(120, 820),
        )
        self.candles.append(candle)
        self.current_price = candle.close
        return candle

    def latest_candle(self) -> Candle:
        return self.candles[-1].model_copy(deep=True)

    def snapshot(self, limit: int | None = None) -> list[Candle]:
        values = [c.model_copy(deep=True) for c in self.candles]
        return values[-limit:] if limit else values

    def price_change(self) -> tuple[float, float]:
        session = rth_candles(self.snapshot())
        reference = session[0].open if session else self.candles[0].open
        change = self.current_price - reference
        return change, (change / reference * 100) if reference else 0.0

    def overview(self) -> list[MarketOverviewItem]:
        nq_change, nq_percent = self.price_change()
        ratio = self.current_price / settings.simulation_start_price
        synthetic = [
            ("NQ1!", self.current_price, nq_change, nq_percent),
            ("ES1!", 5521.0 * (0.999 + (ratio - 1) * .68), nq_change * .17, nq_percent * .72),
            ("YM1!", 39850.0 * (0.9995 + (ratio - 1) * .42), nq_change * .82, nq_percent * .48),
            ("RTY1!", 2083.4 * (0.999 + (ratio - 1) * .86), nq_change * .07, nq_percent * .91),
            ("VIX", max(9.5, 12.45 - nq_percent * 1.65), -nq_percent * .22, -nq_percent * 1.28),
        ]
        return [MarketOverviewItem(symbol=s, price=round(p, 2), change=round(c, 2), change_percent=round(pc, 2)) for s, p, c, pc in synthetic]

    def health(self) -> dict:
        return {"mode": self.mode, "data_source": self.data_source, "connected": True, "last_error": self.last_error, "symbol": self.symbol, "candle_count": len(self.candles)}


class DatabentoMarketDataService:
    mode = "live"
    data_source = "databento"
    symbol = "NQ"

    def __init__(self, max_candles: int = 2400):
        self.candles: deque[Candle] = deque(maxlen=max_candles)
        self.current_price = settings.simulation_start_price
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
            logger.exception("Unable to start Databento market data")
            if not self.candles:
                fallback = SimulatedMarketDataService()
                self.candles.extend(fallback.snapshot())
                self.current_price = fallback.current_price

    async def stop(self) -> None:
        if self._live_client is not None:
            try:
                self._live_client.stop()
            except Exception:
                logger.debug("Databento live stop failed", exc_info=True)
        self.connected = False

    def _import_db(self):
        try:
            import databento as db
        except ImportError as exc:
            raise RuntimeError("Install Databento with: python -m pip install -U databento") from exc
        return db

    def _seed_history(self) -> None:
        db = self._import_db()
        client = db.Historical(key=settings.databento_api_key)
        requested_end = datetime.now(timezone.utc)
        end = available_dataset_end(client, settings.databento_dataset, "ohlcv-1m", requested_end)
        start = end - timedelta(days=max(settings.databento_history_days, 2))
        store = client.timeseries.get_range(
            dataset=settings.databento_dataset, schema="ohlcv-1m", stype_in="continuous",
            symbols=[settings.databento_futures_symbol], start=start.isoformat(), end=end.isoformat(),
        )
        loaded = [Candle(time=_record_time(r), open=round(_pretty_price(r, "open"), 2), high=round(_pretty_price(r, "high"), 2), low=round(_pretty_price(r, "low"), 2), close=round(_pretty_price(r, "close"), 2), volume=int(r.volume)) for r in store if all(hasattr(r, f) for f in ("open", "high", "low", "close", "volume"))]
        loaded.sort(key=lambda c: c.time)
        with self._lock:
            self.candles.clear()
            self.candles.extend(loaded[-settings.databento_history_limit:])
            if self.candles:
                self.current_price = self.candles[-1].close
        if not loaded:
            raise RuntimeError("Databento returned no NQ historical bars for the configured symbol.")

    def _run_live(self) -> None:
        try:
            db = self._import_db()
            client = db.Live(key=settings.databento_api_key, reconnect_policy="reconnect")
            self._live_client = client
            client.subscribe(dataset=settings.databento_dataset, schema="ohlcv-1s", stype_in="continuous", symbols=[settings.databento_futures_symbol])
            client.add_callback(self._on_record, self._on_callback_error)
            self.connected = True
            client.start(); client.block_for_close()
        except Exception as exc:
            self.connected = False; self.last_error = str(exc)
            logger.exception("Databento live NQ stream stopped")

    def _on_callback_error(self, exc: Exception) -> None:
        self.last_error = str(exc)

    def _on_record(self, record: Any) -> None:
        if hasattr(record, "stype_out_symbol"):
            self.raw_symbol = str(record.stype_out_symbol); return
        if not all(hasattr(record, f) for f in ("open", "high", "low", "close", "volume")):
            return
        minute = _record_time(record).replace(second=0, microsecond=0)
        open_px, high_px, low_px, close_px = (_pretty_price(record, f) for f in ("open", "high", "low", "close"))
        volume = int(record.volume)
        with self._lock:
            if self.candles and self.candles[-1].time == minute:
                last = self.candles[-1]
                self.candles[-1] = Candle(time=minute, open=last.open, high=round(max(last.high, high_px), 2), low=round(min(last.low, low_px), 2), close=round(close_px, 2), volume=last.volume + volume)
            else:
                self.candles.append(Candle(time=minute, open=round(open_px, 2), high=round(high_px, 2), low=round(low_px, 2), close=round(close_px, 2), volume=volume))
            self.current_price = round(close_px, 2); self.connected = True; self.last_error = None

    def latest_candle(self) -> Candle:
        with self._lock:
            if not self.candles:
                raise RuntimeError("No NQ candles are available.")
            return self.candles[-1].model_copy(deep=True)

    def snapshot(self, limit: int | None = None) -> list[Candle]:
        with self._lock:
            values = [c.model_copy(deep=True) for c in self.candles]
        return values[-limit:] if limit else values

    def price_change(self) -> tuple[float, float]:
        session = rth_candles(self.snapshot())
        reference = session[0].open if session else self.snapshot()[0].open
        change = self.current_price - reference
        return change, (change / reference * 100) if reference else 0.0

    def overview(self) -> list[MarketOverviewItem]:
        change, percent = self.price_change()
        return [MarketOverviewItem(symbol="NQ1!", price=round(self.current_price, 2), change=round(change, 2), change_percent=round(percent, 2))]

    def health(self) -> dict:
        return {"mode": self.mode, "data_source": self.data_source, "connected": self.connected, "last_error": self.last_error, "symbol": settings.databento_futures_symbol, "raw_symbol": self.raw_symbol, "candle_count": len(self.candles)}


market_data_service = DatabentoMarketDataService() if settings.use_databento else SimulatedMarketDataService()
