import asyncio
import logging
import random
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import sin
from typing import Any
from zoneinfo import ZoneInfo

from backend.core.config import settings
from backend.models.schemas import Candle, MarketOverviewItem
from backend.services.instruments import INSTRUMENTS, InstrumentProfile, get_instrument, instrument_registry

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


def rth_candles(
    candles: list[Candle],
    now: datetime | None = None,
    profile: InstrumentProfile | None = None,
) -> list[Candle]:
    if not candles:
        return []
    instrument = profile or instrument_registry.active
    tz = ZoneInfo(settings.rth_timezone)
    local_now = (now or candles[-1].time).astimezone(tz)
    session_date = local_now.date()
    start_local = datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        instrument.rth_start_hour,
        instrument.rth_start_minute,
        tzinfo=tz,
    )
    end_local = datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        instrument.rth_end_hour,
        instrument.rth_end_minute,
        tzinfo=tz,
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
        pstart = datetime(
            prior.year,
            prior.month,
            prior.day,
            instrument.rth_start_hour,
            instrument.rth_start_minute,
            tzinfo=tz,
        ).astimezone(timezone.utc)
        pend = datetime(
            prior.year,
            prior.month,
            prior.day,
            instrument.rth_end_hour,
            instrument.rth_end_minute,
            tzinfo=tz,
        ).astimezone(timezone.utc)
        values = [c for c in candles if pstart <= c.time < pend]
        if values:
            return values

    fallback_count = max(60, int(((instrument.rth_end_hour * 60 + instrument.rth_end_minute) - (instrument.rth_start_hour * 60 + instrument.rth_start_minute))))
    return candles[-fallback_count:]


class SimulatedMarketDataService:
    mode = "simulated"
    data_source = "local-generator"
    connected = True
    last_error: str | None = None

    def __init__(self, max_candles: int = 2400, profile: InstrumentProfile | None = None):
        self.max_candles = max_candles
        self.instrument = profile or instrument_registry.active
        self.current_price = self.instrument.simulation_start_price
        self.candles: deque[Candle] = deque(maxlen=max_candles)
        self._rng = random.Random(57255 + sum(ord(char) for char in self.instrument.symbol))
        self._task: asyncio.Task | None = None
        self._lock = threading.RLock()
        self._seed_history()

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

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
            self._task = None

    async def switch_symbol(self, symbol: str) -> dict:
        profile = get_instrument(symbol)
        instrument_registry.select(profile.symbol)
        with self._lock:
            self.instrument = profile
            self.current_price = profile.simulation_start_price
            self._rng = random.Random(57255 + sum(ord(char) for char in profile.symbol))
            self.candles.clear()
            self._seed_history()
            self.last_error = None
        return self.health()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(max(1, settings.update_interval_seconds))
            with self._lock:
                self._append_candle()

    def _seed_history(self) -> None:
        profile = self.instrument
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        count = 1920
        price = profile.simulation_start_price - profile.simulation_history_width
        for index in range(count):
            timestamp = now - timedelta(minutes=count - index)
            progress = index / max(1, count - 1)
            target = (
                profile.simulation_start_price
                - profile.simulation_history_width
                + progress * profile.simulation_history_width
                + profile.simulation_wave_slow * sin(index / 73)
                + profile.simulation_wave_fast * sin(index / 19)
            )
            open_price = price
            close = open_price + (target - open_price) * 0.12 + self._rng.gauss(0, profile.simulation_noise)
            wick_base = max(profile.tick_size, profile.simulation_noise * 0.42)
            high = max(open_price, close) + abs(self._rng.gauss(wick_base, wick_base * 0.55))
            low = min(open_price, close) - abs(self._rng.gauss(wick_base, wick_base * 0.55))
            self.candles.append(
                Candle(
                    time=timestamp,
                    open=round(open_price, profile.price_precision),
                    high=round(high, profile.price_precision),
                    low=round(low, profile.price_precision),
                    close=round(close, profile.price_precision),
                    volume=self._rng.randint(110, 780),
                )
            )
            price = close
        self.current_price = self.candles[-1].close

    def _append_candle(self) -> Candle:
        profile = self.instrument
        last = self.candles[-1]
        open_price = last.close
        recent_direction = last.close - self.candles[-20].close
        drift = profile.tick_size * (0.4 if recent_direction >= 0 else -0.24)
        close = open_price + drift + self._rng.gauss(0, profile.simulation_noise * 1.08)
        wick_base = max(profile.tick_size, profile.simulation_noise * 0.38)
        candle = Candle(
            time=last.time + timedelta(minutes=1),
            open=round(open_price, profile.price_precision),
            high=round(max(open_price, close) + abs(self._rng.gauss(wick_base, wick_base * 0.55)), profile.price_precision),
            low=round(min(open_price, close) - abs(self._rng.gauss(wick_base, wick_base * 0.55)), profile.price_precision),
            close=round(close, profile.price_precision),
            volume=self._rng.randint(120, 820),
        )
        self.candles.append(candle)
        self.current_price = candle.close
        return candle

    def latest_candle(self) -> Candle:
        with self._lock:
            return self.candles[-1].model_copy(deep=True)

    def snapshot(self, limit: int | None = None) -> list[Candle]:
        with self._lock:
            values = [c.model_copy(deep=True) for c in self.candles]
        return values[-limit:] if limit else values

    def price_change(self) -> tuple[float, float]:
        session = rth_candles(self.snapshot(), profile=self.instrument)
        reference = session[0].open if session else self.candles[0].open
        change = self.current_price - reference
        return change, (change / reference * 100) if reference else 0.0

    def overview(self) -> list[MarketOverviewItem]:
        change, percent = self.price_change()
        return [
            MarketOverviewItem(
                symbol=self.instrument.display_symbol,
                price=round(self.current_price, self.instrument.price_precision),
                change=round(change, self.instrument.price_precision),
                change_percent=round(percent, 2),
            )
        ]

    def health(self) -> dict:
        return {
            "mode": self.mode,
            "data_source": self.data_source,
            "connected": True,
            "last_error": self.last_error,
            "symbol": self.symbol,
            "futures_symbol": self.instrument.futures_continuous,
            "raw_symbol": None,
            "candle_count": len(self.candles),
            "instrument": self.instrument.public_dict(),
        }


@dataclass(slots=True)
class _MarketHistoryCache:
    candles: list[Candle]
    current_price: float
    raw_symbol: str | None
    loaded_at: datetime


class DatabentoMarketDataService:
    mode = "live"
    data_source = "databento"

    def __init__(self, max_candles: int = 2400):
        self.max_candles = max_candles
        self.instrument = instrument_registry.active
        self.candles: deque[Candle] = deque(maxlen=max_candles)
        self.current_price = self.instrument.simulation_start_price
        self.connected = False
        self.last_error: str | None = None
        self.raw_symbol: str | None = None
        self.warming = False
        self.history_cached = False
        self._live_client = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._switch_lock = asyncio.Lock()
        self._started = False
        self._generation = 0
        self._history_cache: dict[str, _MarketHistoryCache] = {}
        self._history_tasks: dict[str, asyncio.Task] = {}
        self._prewarm_task: asyncio.Task | None = None
        self._live_overlay: dict[datetime, Candle] = {}

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        # The default market is fully loaded before the trade engine starts.
        await self._activate_profile(self.instrument, wait_for_history=True)
        if settings.databento_prewarm_markets:
            self._prewarm_task = asyncio.create_task(
                self._prewarm_remaining_markets(),
                name="databento-market-prewarm",
            )

    async def stop(self) -> None:
        self._generation += 1
        self._stop_live_client()
        self.connected = False
        tasks = list(self._history_tasks.values())
        if self._prewarm_task:
            tasks.append(self._prewarm_task)
        for task in tasks:
            if task and not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def switch_symbol(self, symbol: str) -> dict:
        profile = get_instrument(symbol)
        async with self._switch_lock:
            if profile.symbol == self.instrument.symbol and self.candles:
                instrument_registry.select(profile.symbol)
                return self.health()
            instrument_registry.select(profile.symbol)
            # Switching now returns immediately. Cached history or a local preview is
            # displayed first while Databento backfills in the background.
            await self._activate_profile(profile, wait_for_history=False)
        return self.health()

    async def _activate_profile(self, profile: InstrumentProfile, wait_for_history: bool) -> None:
        self._remember_active_cache()
        self._generation += 1
        generation = self._generation
        self._stop_live_client()

        cache = self._history_cache.get(profile.symbol)
        cache_age = (datetime.now(timezone.utc) - cache.loaded_at).total_seconds() if cache else None
        cache_is_fresh = bool(cache and cache_age is not None and cache_age <= settings.databento_market_cache_seconds)

        with self._lock:
            self.instrument = profile
            self.raw_symbol = cache.raw_symbol if cache else None
            self.connected = False
            self.last_error = None
            self._live_overlay = {}
            self.candles.clear()
            if cache:
                self.candles.extend(candle.model_copy(deep=True) for candle in cache.candles[-self.max_candles:])
                self.current_price = cache.current_price
                self.history_cached = True
            else:
                # A deterministic preview makes the UI responsive on the first visit
                # to a market. It is replaced by real history as soon as backfill ends.
                preview = SimulatedMarketDataService(max_candles=self.max_candles, profile=profile)
                self.candles.extend(preview.snapshot())
                self.current_price = preview.current_price
                self.history_cached = False
            self.warming = not cache_is_fresh

        if wait_for_history:
            try:
                loaded = await asyncio.to_thread(self._load_history, profile)
                self._store_history(profile, loaded)
                self._merge_active_history(profile, loaded, generation)
            except Exception as exc:
                self.last_error = str(exc)
                self.warming = False
                logger.exception("Unable to seed Databento history for %s", profile.symbol)
            if self._started and generation == self._generation:
                self._start_live(profile, generation)
            return

        if self._started and generation == self._generation:
            self._start_live(profile, generation)
        if not cache_is_fresh:
            self._schedule_history_refresh(profile, generation)

    def _remember_active_cache(self) -> None:
        with self._lock:
            if not self.candles or not self.history_cached:
                return
            self._history_cache[self.instrument.symbol] = _MarketHistoryCache(
                candles=[candle.model_copy(deep=True) for candle in self.candles],
                current_price=self.current_price,
                raw_symbol=self.raw_symbol,
                loaded_at=datetime.now(timezone.utc),
            )

    def _schedule_history_refresh(self, profile: InstrumentProfile, generation: int | None = None) -> None:
        existing = self._history_tasks.get(profile.symbol)
        if existing and not existing.done():
            return
        task = asyncio.create_task(
            self._refresh_history(profile, generation),
            name=f"databento-history-{profile.symbol.lower()}",
        )
        self._history_tasks[profile.symbol] = task
        task.add_done_callback(lambda _task, symbol=profile.symbol: self._history_tasks.pop(symbol, None))

    async def _refresh_history(self, profile: InstrumentProfile, generation: int | None = None) -> None:
        try:
            loaded = await asyncio.to_thread(self._load_history, profile)
            self._store_history(profile, loaded)
            if profile.symbol == self.instrument.symbol:
                self._merge_active_history(profile, loaded, generation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if profile.symbol == self.instrument.symbol:
                self.last_error = str(exc)
                self.warming = False
            logger.exception("Databento history refresh failed for %s", profile.symbol)

    async def _prewarm_remaining_markets(self) -> None:
        # Load the other five instruments one at a time to avoid a burst of paid
        # historical requests. Once warmed, switching is normally sub-second.
        for profile in INSTRUMENTS.values():
            if profile.symbol == self.instrument.symbol or profile.symbol in self._history_cache:
                continue
            try:
                loaded = await asyncio.to_thread(self._load_history, profile)
                self._store_history(profile, loaded)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unable to prewarm %s history", profile.symbol)
            await asyncio.sleep(max(0.0, settings.databento_prewarm_delay_seconds))

    def _store_history(self, profile: InstrumentProfile, loaded: list[Candle]) -> None:
        if not loaded:
            return
        self._history_cache[profile.symbol] = _MarketHistoryCache(
            candles=[candle.model_copy(deep=True) for candle in loaded[-self.max_candles:]],
            current_price=loaded[-1].close,
            raw_symbol=None,
            loaded_at=datetime.now(timezone.utc),
        )

    def _merge_active_history(
        self,
        profile: InstrumentProfile,
        loaded: list[Candle],
        generation: int | None,
    ) -> None:
        with self._lock:
            if profile.symbol != self.instrument.symbol:
                return
            if generation is not None and generation != self._generation:
                return
            merged = {candle.time: candle.model_copy(deep=True) for candle in loaded}
            # Preserve real live bars received while the historical request was running.
            for candle_time, candle in self._live_overlay.items():
                merged[candle_time] = candle.model_copy(deep=True)
            values = sorted(merged.values(), key=lambda candle: candle.time)[-self.max_candles:]
            if not values:
                return
            self.candles.clear()
            self.candles.extend(values)
            self.current_price = values[-1].close
            self.history_cached = True
            self.warming = False
            self.last_error = None
            self._history_cache[profile.symbol] = _MarketHistoryCache(
                candles=[candle.model_copy(deep=True) for candle in values],
                current_price=self.current_price,
                raw_symbol=self.raw_symbol,
                loaded_at=datetime.now(timezone.utc),
            )

    def _stop_live_client(self) -> None:
        client = self._live_client
        self._live_client = None
        if client is not None:
            try:
                client.stop()
            except Exception:
                logger.debug("Databento live stop failed", exc_info=True)

    def _start_live(self, profile: InstrumentProfile, generation: int) -> None:
        self._thread = threading.Thread(
            target=self._run_live,
            args=(profile, generation),
            name=f"databento-{profile.symbol.lower()}-live",
            daemon=True,
        )
        self._thread.start()

    def _import_db(self):
        try:
            import databento as db
        except ImportError as exc:
            raise RuntimeError("Install Databento with: python -m pip install -U databento") from exc
        return db

    def _load_history(self, profile: InstrumentProfile) -> list[Candle]:
        db = self._import_db()
        client = db.Historical(key=settings.databento_api_key)
        requested_end = datetime.now(timezone.utc)
        end = available_dataset_end(client, settings.databento_dataset, "ohlcv-1m", requested_end)
        start = end - timedelta(days=max(settings.databento_history_days, 2))
        store = client.timeseries.get_range(
            dataset=settings.databento_dataset,
            schema="ohlcv-1m",
            stype_in="continuous",
            symbols=[profile.futures_continuous],
            start=start.isoformat(),
            end=end.isoformat(),
        )
        loaded = [
            Candle(
                time=_record_time(record),
                open=round(_pretty_price(record, "open"), profile.price_precision),
                high=round(_pretty_price(record, "high"), profile.price_precision),
                low=round(_pretty_price(record, "low"), profile.price_precision),
                close=round(_pretty_price(record, "close"), profile.price_precision),
                volume=int(record.volume),
            )
            for record in store
            if all(hasattr(record, field) for field in ("open", "high", "low", "close", "volume"))
        ]
        loaded.sort(key=lambda candle: candle.time)
        if not loaded:
            raise RuntimeError(f"Databento returned no {profile.symbol} historical bars for {profile.futures_continuous}.")
        return loaded[-settings.databento_history_limit:]

    def _run_live(self, profile: InstrumentProfile, generation: int) -> None:
        try:
            db = self._import_db()
            client = db.Live(key=settings.databento_api_key, reconnect_policy="reconnect")
            if generation != self._generation:
                return
            self._live_client = client
            client.subscribe(
                dataset=settings.databento_dataset,
                schema="ohlcv-1s",
                stype_in="continuous",
                symbols=[profile.futures_continuous],
            )
            client.add_callback(
                lambda record: self._on_record(record, profile, generation),
                lambda exc: self._on_callback_error(exc, generation),
            )
            self.connected = True
            client.start()
            client.block_for_close()
        except Exception as exc:
            if generation == self._generation:
                self.connected = False
                self.last_error = str(exc)
            logger.exception("Databento live %s stream stopped", profile.symbol)

    def _on_callback_error(self, exc: Exception, generation: int) -> None:
        if generation == self._generation:
            self.last_error = str(exc)

    def _on_record(self, record: Any, profile: InstrumentProfile, generation: int) -> None:
        if generation != self._generation or profile.symbol != self.instrument.symbol:
            return
        if hasattr(record, "stype_out_symbol"):
            self.raw_symbol = str(record.stype_out_symbol)
            return
        if not all(hasattr(record, field) for field in ("open", "high", "low", "close", "volume")):
            return
        minute = _record_time(record).replace(second=0, microsecond=0)
        open_px, high_px, low_px, close_px = (_pretty_price(record, field) for field in ("open", "high", "low", "close"))
        volume = int(record.volume)
        with self._lock:
            if generation != self._generation:
                return
            if self.candles and self.candles[-1].time == minute:
                last = self.candles[-1]
                candle = Candle(
                    time=minute,
                    open=last.open,
                    high=round(max(last.high, high_px), profile.price_precision),
                    low=round(min(last.low, low_px), profile.price_precision),
                    close=round(close_px, profile.price_precision),
                    volume=last.volume + volume,
                )
                self.candles[-1] = candle
            else:
                candle = Candle(
                    time=minute,
                    open=round(open_px, profile.price_precision),
                    high=round(high_px, profile.price_precision),
                    low=round(low_px, profile.price_precision),
                    close=round(close_px, profile.price_precision),
                    volume=volume,
                )
                self.candles.append(candle)
            self._live_overlay[minute] = candle.model_copy(deep=True)
            self.current_price = round(close_px, profile.price_precision)
            self.connected = True
            self.last_error = None

    def latest_candle(self) -> Candle:
        with self._lock:
            if not self.candles:
                raise RuntimeError(f"No {self.instrument.symbol} candles are available.")
            return self.candles[-1].model_copy(deep=True)

    def snapshot(self, limit: int | None = None) -> list[Candle]:
        with self._lock:
            values = [c.model_copy(deep=True) for c in self.candles]
        return values[-limit:] if limit else values

    def price_change(self) -> tuple[float, float]:
        values = self.snapshot()
        if not values:
            return 0.0, 0.0
        session = rth_candles(values, profile=self.instrument)
        reference = session[0].open if session else values[0].open
        change = self.current_price - reference
        return change, (change / reference * 100) if reference else 0.0

    def overview(self) -> list[MarketOverviewItem]:
        change, percent = self.price_change()
        return [
            MarketOverviewItem(
                symbol=self.instrument.display_symbol,
                price=round(self.current_price, self.instrument.price_precision),
                change=round(change, self.instrument.price_precision),
                change_percent=round(percent, 2),
            )
        ]

    def health(self) -> dict:
        cache = self._history_cache.get(self.instrument.symbol)
        cache_age = (datetime.now(timezone.utc) - cache.loaded_at).total_seconds() if cache else None
        return {
            "mode": self.mode,
            "data_source": self.data_source,
            "connected": self.connected,
            "last_error": self.last_error,
            "symbol": self.instrument.symbol,
            "futures_symbol": self.instrument.futures_continuous,
            "raw_symbol": self.raw_symbol,
            "candle_count": len(self.candles),
            "warming": self.warming,
            "history_cached": self.history_cached,
            "cache_age_seconds": round(cache_age, 1) if cache_age is not None else None,
            "cached_symbols": sorted(self._history_cache),
            "instrument": self.instrument.public_dict(),
        }


market_data_service = DatabentoMarketDataService() if settings.use_databento else SimulatedMarketDataService()
