import asyncio
import logging
import random
import threading
from statistics import median
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite, sin
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




def _plausible_live_ohlc(
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    reference: float | None,
    tick_size: float,
) -> bool:
    """Reject corrupt one-second records before they can deform minute candles.

    Databento reconnects can occasionally replay stale records and any malformed
    OHLC value is especially destructive on a 1m/2m chart because it expands the
    whole price scale.  The guard is deliberately generous enough for real
    futures volatility while still rejecting impossible jumps and giant wicks.
    """
    values = (open_px, high_px, low_px, close_px)
    if not all(isfinite(float(value)) and float(value) > 0 for value in values):
        return False
    if high_px < max(open_px, close_px) or low_px > min(open_px, close_px) or high_px < low_px:
        return False
    if reference is None or not isfinite(reference) or reference <= 0:
        return True

    allowed_move = max(reference * 0.015, max(float(tick_size), 1e-9) * 500)
    if abs(open_px - reference) > allowed_move:
        return False
    if max(abs(high_px - reference), abs(low_px - reference), abs(close_px - reference)) > allowed_move:
        return False
    return True

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


def _valid_candle(candle: Candle) -> bool:
    values = (candle.open, candle.high, candle.low, candle.close)
    return (
        all(isinstance(value, (int, float)) for value in values)
        and all(float("-inf") < float(value) < float("inf") for value in values)
        and candle.high >= max(candle.open, candle.close)
        and candle.low <= min(candle.open, candle.close)
        and candle.high >= candle.low
        and candle.open > 0
        and candle.close > 0
    )


def _sanitize_candles(candles: list[Candle], max_jump_ratio: float = 0.12) -> list[Candle]:
    """Return ordered, unique OHLC bars while dropping impossible isolated jumps.

    A continuous futures series can legitimately gap across sessions, but a 12%
    one-bar jump followed immediately by a return is almost always a mixed symbol
    or malformed record. The history/live continuity guard below handles whole
    series mismatches separately.
    """
    unique: dict[datetime, Candle] = {}
    for candle in candles:
        if _valid_candle(candle):
            unique[candle.time] = candle.model_copy(deep=True)
    ordered = sorted(unique.values(), key=lambda item: item.time)
    if len(ordered) < 3:
        return ordered

    clean: list[Candle] = [ordered[0]]
    recent_ranges: list[float] = [max(ordered[0].high - ordered[0].low, 0.0)]
    for index in range(1, len(ordered) - 1):
        previous = clean[-1]
        current = ordered[index]
        following = ordered[index + 1]
        reference = max(abs(previous.close), 1e-9)
        jump = abs(current.open - previous.close) / reference
        return_jump = abs(following.open - current.close) / max(abs(current.close), 1e-9)
        candle_range = max(current.high - current.low, 0.0)
        body = abs(current.close - current.open)
        typical_range = median([value for value in recent_ranges[-30:] if value > 0]) if any(value > 0 for value in recent_ranges[-30:]) else 0.0
        giant_wick = bool(
            typical_range > 0
            and candle_range > max(typical_range * 10, reference * 0.008)
            and body < max(typical_range * 5, candle_range * 0.35)
        )
        # Drop isolated regime spikes and giant one-bar wicks. Preserve sustained
        # repricing and legitimate large-bodied news candles.
        if giant_wick or (jump > max_jump_ratio and return_jump > max_jump_ratio):
            continue
        clean.append(current)
        recent_ranges.append(candle_range)
    last = ordered[-1]
    previous = clean[-1]
    reference = max(abs(previous.close), 1e-9)
    candle_range = max(last.high - last.low, 0.0)
    body = abs(last.close - last.open)
    sample = [value for value in recent_ranges[-30:] if value > 0]
    typical_range = median(sample) if sample else 0.0
    giant_live_wick = bool(
        typical_range > 0
        and candle_range > max(typical_range * 10, reference * 0.008)
        and body < max(typical_range * 4, candle_range * 0.35)
    )
    if not giant_live_wick:
        clean.append(last)
    return clean


def _cme_globex_expected_live(now: datetime | None = None) -> bool:
    """Return whether the main CME Globex futures session should be producing data.

    This prevents the stale-feed watchdog from restarting continuously during
    the normal 5–6 PM ET maintenance break and the weekend closure.
    """
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    weekday = local.weekday()
    minutes = local.hour * 60 + local.minute
    if weekday == 5:  # Saturday
        return False
    if weekday == 6:  # Sunday opens at 6 PM ET
        return minutes >= 18 * 60
    if weekday == 4:  # Friday closes at 5 PM ET
        return minutes < 17 * 60
    return not (17 * 60 <= minutes < 18 * 60)


def _series_gap_ratio(history: list[Candle], live: list[Candle]) -> float | None:
    if not history or not live:
        return None
    history_reference = sum(item.close for item in history[-min(20, len(history)):]) / min(20, len(history))
    live_reference = sum(item.close for item in live[:min(5, len(live)):]) / min(5, len(live))
    if history_reference <= 0:
        return None
    return abs(live_reference - history_reference) / history_reference


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
        self._background_cache: dict[str, list[Candle]] = {}
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

    def cached_snapshot(self, symbol: str, limit: int | None = None) -> list[Candle]:
        profile = get_instrument(symbol)
        if profile.symbol == self.instrument.symbol:
            return self.snapshot(limit=limit)
        with self._lock:
            cached = self._background_cache.get(profile.symbol)
        if cached is None:
            generator = SimulatedMarketDataService(max_candles=self.max_candles, profile=profile)
            cached = generator.snapshot()
            with self._lock:
                self._background_cache[profile.symbol] = cached
        values = [item.model_copy(deep=True) for item in cached]
        return values[-limit:] if limit else values

    async def refresh_symbol_cache(self, symbol: str, force: bool = False) -> list[Candle]:
        return self.cached_snapshot(symbol)

    def cache_status(self, symbol: str) -> dict:
        profile = get_instrument(symbol)
        cached = profile.symbol == self.instrument.symbol or profile.symbol in self._background_cache
        return {"symbol": profile.symbol, "cached": cached, "age_seconds": 0.0 if cached else None}

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
        now = datetime.now(timezone.utc)
        latest = self.candles[-1].time if self.candles else None
        return {
            "mode": self.mode,
            "data_source": self.data_source,
            "connected": True,
            "stream_state": "LIVE",
            "server_time": now,
            "last_record_at": now,
            "last_record_age_seconds": 0.0,
            "last_candle_at": latest,
            "last_candle_age_seconds": round((now - latest).total_seconds(), 1) if latest else None,
            "data_fresh": True,
            "stale_after_seconds": None,
            "reconnect_attempts": 0,
            "total_reconnects": 0,
            "next_retry_at": None,
            "last_disconnect_reason": None,
            "last_error": self.last_error,
            "symbol": self.symbol,
            "futures_symbol": self.instrument.futures_continuous,
            "raw_symbol": None,
            "candle_count": len(self.candles),
            "warming": False,
            "history_cached": True,
            "history_ready": True,
            "history_source": "simulated",
            "data_quality": "SIMULATED",
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
        self.history_source = "none"
        self.data_quality = "WAITING_FOR_HISTORY"
        self._live_client = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._switch_lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._generation = 0
        self._history_cache: dict[str, _MarketHistoryCache] = {}
        self._history_tasks: dict[str, asyncio.Task] = {}
        self._prewarm_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._recovery_task: asyncio.Task | None = None
        self._live_overlay: dict[datetime, Candle] = {}
        self._live_stop_event: threading.Event | None = None
        self.stream_state = "STOPPED"
        self.stream_started_at: datetime | None = None
        self.stream_connected_at: datetime | None = None
        self.last_record_at: datetime | None = None
        self.last_candle_at: datetime | None = None
        self.next_retry_at: datetime | None = None
        self.last_disconnect_reason: str | None = None
        self.reconnect_attempts = 0
        self.total_reconnects = 0

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._event_loop = asyncio.get_running_loop()
        # The default market is fully loaded before the trade engine starts.
        await self._activate_profile(self.instrument, wait_for_history=True)
        self._watchdog_task = asyncio.create_task(
            self._live_watchdog_loop(),
            name="databento-live-watchdog",
        )
        if settings.databento_prewarm_markets:
            self._prewarm_task = asyncio.create_task(
                self._prewarm_remaining_markets(),
                name="databento-market-prewarm",
            )

    async def stop(self) -> None:
        self._started = False
        self._generation += 1
        self._stop_live_client(wait=True)
        self.connected = False
        self.stream_state = "STOPPED"
        tasks = list(self._history_tasks.values())
        for task in (self._prewarm_task, self._watchdog_task, self._recovery_task):
            if task:
                tasks.append(task)
        for task in tasks:
            if task and not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._prewarm_task = None
        self._watchdog_task = None
        self._recovery_task = None
        self._event_loop = None

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
        self._stop_live_client(wait=True)

        cache = self._history_cache.get(profile.symbol)
        cache_age = (datetime.now(timezone.utc) - cache.loaded_at).total_seconds() if cache else None
        cache_is_fresh = bool(cache and cache_age is not None and cache_age <= settings.databento_market_cache_seconds)

        with self._lock:
            self.instrument = profile
            self.raw_symbol = cache.raw_symbol if cache else None
            self.connected = False
            self.last_error = None
            self.stream_state = "CONNECTING"
            self.stream_started_at = None
            self.stream_connected_at = None
            self.last_record_at = None
            self.last_candle_at = None
            self.next_retry_at = None
            self.last_disconnect_reason = None
            self.reconnect_attempts = 0
            self._live_overlay = {}
            self.candles.clear()
            if cache:
                self.candles.extend(candle.model_copy(deep=True) for candle in cache.candles[-self.max_candles:])
                self.current_price = cache.current_price
                self.last_candle_at = self.candles[-1].time if self.candles else None
                self.history_cached = True
                self.history_source = "databento-cache"
                self.data_quality = "READY"
            else:
                # Never mix synthetic preview prices with real Databento ticks.
                # The chart shows a clear syncing state until real bars arrive.
                self.current_price = 0.0
                self.history_cached = False
                self.history_source = "live-pending-history"
                self.data_quality = "WAITING_FOR_HISTORY"
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
        # Warm only the configured desk markets one at a time to avoid a burst of
        # paid historical requests. NQ/ES/GC are the default fast-switch set.
        requested = {item.strip().upper() for item in str(settings.databento_prewarm_symbols or "NQ,ES,GC").split(",") if item.strip()}
        for profile in INSTRUMENTS.values():
            if profile.symbol not in requested:
                continue
            if profile.symbol == self.instrument.symbol or profile.symbol in self._history_cache:
                continue
            try:
                existing = self._history_tasks.get(profile.symbol)
                if existing and not existing.done():
                    await existing
                else:
                    task = asyncio.create_task(
                        self._refresh_history(profile, None),
                        name=f"databento-prewarm-{profile.symbol.lower()}",
                    )
                    self._history_tasks[profile.symbol] = task
                    task.add_done_callback(lambda _task, symbol=profile.symbol: self._history_tasks.pop(symbol, None))
                    await task
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unable to prewarm %s history", profile.symbol)
            await asyncio.sleep(max(0.0, settings.databento_prewarm_delay_seconds))

    def _store_history(self, profile: InstrumentProfile, loaded: list[Candle]) -> None:
        loaded = _sanitize_candles(loaded)
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
            loaded = _sanitize_candles(loaded)
            live_values = _sanitize_candles(list(self._live_overlay.values()))
            gap_ratio = _series_gap_ratio(loaded, live_values)
            if gap_ratio is not None and gap_ratio > 0.08:
                # Contract/provenance mismatch: never stitch two different price regimes.
                # Keep only verified live bars while the next historical refresh retries.
                values = live_values[-self.max_candles:]
                if values:
                    self.candles.clear()
                    self.candles.extend(values)
                    self.current_price = values[-1].close
                self.history_cached = False
                self.history_source = "live-only-mismatch"
                self.data_quality = "CONTRACT_MISMATCH"
                self.warming = True
                self.last_error = (
                    f"Rejected {profile.symbol} history/live merge: price regimes differed by "
                    f"{gap_ratio * 100:.1f}%."
                )
                logger.error(self.last_error)
                return

            merged = {candle.time: candle.model_copy(deep=True) for candle in loaded}
            # Preserve real live bars received while the historical request was running.
            for candle_time, candle in self._live_overlay.items():
                merged[candle_time] = candle.model_copy(deep=True)
            values = _sanitize_candles(sorted(merged.values(), key=lambda candle: candle.time))[-self.max_candles:]
            if not values:
                return
            self.candles.clear()
            self.candles.extend(values)
            self.current_price = values[-1].close
            self.last_candle_at = values[-1].time
            self.history_cached = True
            self.history_source = "databento"
            self.data_quality = "READY"
            self.warming = False
            self.last_error = None
            self._history_cache[profile.symbol] = _MarketHistoryCache(
                candles=[candle.model_copy(deep=True) for candle in values],
                current_price=self.current_price,
                raw_symbol=self.raw_symbol,
                loaded_at=datetime.now(timezone.utc),
            )

    def _stop_live_client(self, wait: bool = False) -> None:
        stop_event = self._live_stop_event
        if stop_event is not None:
            stop_event.set()
        client = self._live_client
        self._live_client = None
        if client is not None:
            try:
                client.stop()
            except Exception:
                logger.debug("Databento live stop failed", exc_info=True)
        thread = self._thread
        if (
            wait
            and thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=max(0.0, float(settings.databento_stop_join_seconds)))
        if thread is not None and not thread.is_alive():
            self._thread = None
        self._live_stop_event = None

    def _start_live(self, profile: InstrumentProfile, generation: int) -> None:
        stop_event = threading.Event()
        self._live_stop_event = stop_event
        with self._lock:
            self.stream_state = "CONNECTING"
            self.stream_started_at = datetime.now(timezone.utc)
            self.next_retry_at = None
        self._thread = threading.Thread(
            target=self._run_live,
            args=(profile, generation, stop_event),
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
        loaded = _sanitize_candles(loaded)
        if not loaded:
            raise RuntimeError(f"Databento returned no {profile.symbol} historical bars for {profile.futures_continuous}.")
        return loaded[-settings.databento_history_limit:]

    def _load_history_since(self, profile: InstrumentProfile, start: datetime) -> list[Candle]:
        db = self._import_db()
        client = db.Historical(key=settings.databento_api_key)
        requested_end = datetime.now(timezone.utc)
        end = available_dataset_end(client, settings.databento_dataset, "ohlcv-1m", requested_end)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start >= end:
            return []
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
        return _sanitize_candles(loaded)

    def _queue_gap_recovery(
        self,
        profile: InstrumentProfile,
        generation: int,
        reason: str,
    ) -> None:
        loop = self._event_loop
        if loop is None or not loop.is_running():
            return
        loop.call_soon_threadsafe(
            self._ensure_gap_recovery_task,
            profile,
            generation,
            reason,
        )

    def _ensure_gap_recovery_task(
        self,
        profile: InstrumentProfile,
        generation: int,
        reason: str,
    ) -> None:
        if not self._started or generation != self._generation:
            return
        if self._recovery_task and not self._recovery_task.done():
            return
        self._recovery_task = asyncio.create_task(
            self._recover_active_gap(profile, generation, reason),
            name=f"databento-gap-recovery-{profile.symbol.lower()}",
        )

    async def _recover_active_gap(
        self,
        profile: InstrumentProfile,
        generation: int,
        reason: str,
    ) -> None:
        try:
            with self._lock:
                if generation != self._generation or profile.symbol != self.instrument.symbol:
                    return
                start = (
                    self.candles[-1].time - timedelta(minutes=2)
                    if self.candles
                    else datetime.now(timezone.utc) - timedelta(minutes=30)
                )
                self.warming = True
                if self.data_quality == "READY":
                    self.data_quality = "RECOVERING_GAP"
            loaded = await asyncio.to_thread(self._load_history_since, profile, start)
            self._merge_active_incremental_history(profile, loaded, generation)
            logger.info(
                "Recovered %s active history after %s (%d bars)",
                profile.symbol,
                reason,
                len(loaded),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if generation == self._generation and profile.symbol == self.instrument.symbol:
                with self._lock:
                    self.last_error = f"Gap recovery failed: {exc}"
                    self.data_quality = "RECOVERY_FAILED"
                    self.warming = False
            logger.exception("Databento gap recovery failed for %s", profile.symbol)

    def _merge_active_incremental_history(
        self,
        profile: InstrumentProfile,
        loaded: list[Candle],
        generation: int,
    ) -> None:
        with self._lock:
            if generation != self._generation or profile.symbol != self.instrument.symbol:
                return
            merged = {candle.time: candle.model_copy(deep=True) for candle in self.candles}
            for candle in _sanitize_candles(loaded):
                merged[candle.time] = candle.model_copy(deep=True)
            for candle_time, candle in self._live_overlay.items():
                merged[candle_time] = candle.model_copy(deep=True)
            values = _sanitize_candles(
                sorted(merged.values(), key=lambda candle: candle.time)
            )[-self.max_candles:]
            if values:
                self.candles.clear()
                self.candles.extend(values)
                self.current_price = values[-1].close
                self.last_candle_at = values[-1].time
                self.history_cached = len(values) >= 50
                self.history_source = "databento-recovered"
                self.data_quality = "READY" if self.history_cached else "LIVE_ONLY"
                self.warming = not self.history_cached
                self._history_cache[profile.symbol] = _MarketHistoryCache(
                    candles=[item.model_copy(deep=True) for item in values],
                    current_price=self.current_price,
                    raw_symbol=self.raw_symbol,
                    loaded_at=datetime.now(timezone.utc),
                )
            else:
                self.warming = False

    async def _live_watchdog_loop(self) -> None:
        interval = max(1, int(settings.databento_live_watchdog_seconds))
        stale_after = max(interval * 2, int(settings.databento_live_stale_seconds))
        while self._started:
            await asyncio.sleep(interval)
            if not self._started:
                return
            with self._lock:
                generation = self._generation
                profile = self.instrument
                state = self.stream_state
                connected = self.connected
                reference = self.last_record_at or self.stream_connected_at or self.stream_started_at
                thread_alive = bool(self._thread and self._thread.is_alive())
            now = datetime.now(timezone.utc)
            age = (now - reference).total_seconds() if reference else None

            if not _cme_globex_expected_live(now):
                continue
            if (
                state in {"CONNECTING", "RECONNECTING"}
                and thread_alive
                and (age is None or age <= stale_after)
            ):
                continue
            if connected and age is not None and age <= stale_after:
                continue

            reason = (
                f"No Databento records received for {age:.0f}s"
                if age is not None and age > stale_after
                else "Databento live worker stopped"
            )
            await self._restart_active_stream(profile, generation, reason)

    async def _restart_active_stream(
        self,
        profile: InstrumentProfile,
        observed_generation: int,
        reason: str,
    ) -> None:
        async with self._switch_lock:
            if (
                not self._started
                or observed_generation != self._generation
                or profile.symbol != self.instrument.symbol
            ):
                return
            with self._lock:
                self.connected = False
                self.stream_state = "STALE"
                self.last_error = reason
                self.last_disconnect_reason = reason
            self._generation += 1
            generation = self._generation
            self._stop_live_client(wait=True)
            with self._lock:
                self.stream_state = "RECONNECTING"
                self.next_retry_at = datetime.now(timezone.utc)
                self.reconnect_attempts += 1
                self.total_reconnects += 1
            self._start_live(profile, generation)
            self._ensure_gap_recovery_task(profile, generation, reason)

    def _run_live(
        self,
        profile: InstrumentProfile,
        generation: int,
        stop_event: threading.Event,
    ) -> None:
        delay = max(0.25, float(settings.databento_reconnect_initial_seconds))
        maximum_delay = max(delay, float(settings.databento_reconnect_max_seconds))
        first_attempt = True

        while (
            self._started
            and generation == self._generation
            and not stop_event.is_set()
        ):
            client = None
            try:
                with self._lock:
                    self.stream_state = "CONNECTING" if first_attempt else "RECONNECTING"
                    self.connected = False
                    self.stream_started_at = datetime.now(timezone.utc)
                    self.next_retry_at = None
                db = self._import_db()
                client = db.Live(key=settings.databento_api_key, reconnect_policy="reconnect")
                if generation != self._generation or stop_event.is_set():
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
                with self._lock:
                    self.connected = True
                    self.stream_state = "LIVE"
                    self.stream_connected_at = datetime.now(timezone.utc)
                    self.next_retry_at = None
                    self.last_error = None
                    if not first_attempt:
                        self.total_reconnects += 1
                if not first_attempt:
                    self._queue_gap_recovery(profile, generation, "Databento stream reconnected")
                client.start()
                client.block_for_close()
                if generation != self._generation or stop_event.is_set() or not self._started:
                    break
                raise RuntimeError("Databento live stream closed unexpectedly")
            except Exception as exc:
                if generation != self._generation or stop_event.is_set() or not self._started:
                    break
                reason = str(exc) or exc.__class__.__name__
                retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                with self._lock:
                    self.connected = False
                    self.stream_state = "RECONNECTING"
                    self.last_error = reason
                    self.last_disconnect_reason = reason
                    self.reconnect_attempts += 1
                    self.next_retry_at = retry_at
                logger.exception(
                    "Databento live %s stream stopped; retrying in %.1fs",
                    profile.symbol,
                    delay,
                )
                if stop_event.wait(delay):
                    break
                delay = min(maximum_delay, delay * 2)
                first_attempt = False
            finally:
                if client is not None:
                    try:
                        client.stop()
                    except Exception:
                        logger.debug("Databento live cleanup failed", exc_info=True)
                if self._live_client is client:
                    self._live_client = None

        if generation == self._generation:
            with self._lock:
                self.connected = False
                if self._started and not stop_event.is_set():
                    self.stream_state = "RECONNECTING"
                else:
                    self.stream_state = "STOPPED"

    def _on_callback_error(self, exc: Exception, generation: int) -> None:
        if generation == self._generation:
            with self._lock:
                self.last_error = str(exc)
                self.last_disconnect_reason = str(exc)
                if self.stream_state == "LIVE":
                    self.stream_state = "DEGRADED"

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
        volume = max(0, int(record.volume))
        with self._lock:
            if generation != self._generation:
                return

            latest = self.candles[-1] if self.candles else None
            reference = latest.close if latest else None
            if not _plausible_live_ohlc(open_px, high_px, low_px, close_px, reference, profile.tick_size):
                logger.warning(
                    "Rejected malformed %s live OHLC record at %s: O=%s H=%s L=%s C=%s",
                    profile.symbol, minute.isoformat(), open_px, high_px, low_px, close_px,
                )
                return

            target_index: int | None = None
            if latest and minute <= latest.time:
                # Reconnects may replay a recent second. Merge it into the existing
                # minute instead of appending an out-of-order candle. Older replayed
                # records are ignored so snapshots always remain strictly ordered.
                for index in range(len(self.candles) - 1, max(-1, len(self.candles) - 6), -1):
                    if self.candles[index].time == minute:
                        target_index = index
                        break
                if target_index is None and minute < latest.time:
                    return

            if target_index is not None:
                existing = self.candles[target_index]
                candle = Candle(
                    time=minute,
                    open=existing.open,
                    high=round(max(existing.high, high_px), profile.price_precision),
                    low=round(min(existing.low, low_px), profile.price_precision),
                    close=round(close_px, profile.price_precision),
                    volume=existing.volume + volume,
                )
                self.candles[target_index] = candle
            elif latest and latest.time == minute:
                candle = Candle(
                    time=minute,
                    open=latest.open,
                    high=round(max(latest.high, high_px), profile.price_precision),
                    low=round(min(latest.low, low_px), profile.price_precision),
                    close=round(close_px, profile.price_precision),
                    volume=latest.volume + volume,
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

            now = datetime.now(timezone.utc)
            self._live_overlay[minute] = candle.model_copy(deep=True)
            self.current_price = candle.close
            self.connected = True
            self.stream_state = "LIVE"
            self.last_record_at = now
            self.last_candle_at = candle.time
            self.next_retry_at = None
            self.reconnect_attempts = 0
            if not self.history_cached:
                self.history_source = "live-pending-history"
                self.data_quality = "LIVE_ONLY"
            elif self.data_quality in {"STALE", "RECOVERING_GAP", "RECOVERY_FAILED"}:
                self.data_quality = "READY"
                self.warming = False
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

    def cached_snapshot(self, symbol: str, limit: int | None = None) -> list[Candle]:
        profile = get_instrument(symbol)
        with self._lock:
            if profile.symbol == self.instrument.symbol:
                values = [item.model_copy(deep=True) for item in self.candles]
            else:
                cache = self._history_cache.get(profile.symbol)
                values = [item.model_copy(deep=True) for item in cache.candles] if cache else []
        return values[-limit:] if limit else values

    async def refresh_symbol_cache(self, symbol: str, force: bool = False) -> list[Candle]:
        profile = get_instrument(symbol)
        if profile.symbol == self.instrument.symbol and self.candles:
            return self.snapshot()
        with self._lock:
            cache = self._history_cache.get(profile.symbol)
        age = (datetime.now(timezone.utc) - cache.loaded_at).total_seconds() if cache else None
        refresh_after = max(30, min(
            int(settings.databento_market_cache_seconds),
            int(settings.multi_market_history_refresh_seconds),
        ))
        if cache and not force and age is not None and age <= refresh_after:
            return self.cached_snapshot(profile.symbol)

        existing = self._history_tasks.get(profile.symbol)
        if existing and not existing.done():
            await existing
        else:
            coroutine = self._refresh_incremental_history(profile) if cache else self._refresh_history(profile, None)
            task = asyncio.create_task(
                coroutine,
                name=f"databento-radar-history-{profile.symbol.lower()}",
            )
            self._history_tasks[profile.symbol] = task
            task.add_done_callback(lambda _task, symbol=profile.symbol: self._history_tasks.pop(symbol, None))
            await task
        return self.cached_snapshot(profile.symbol)

    async def _refresh_incremental_history(self, profile: InstrumentProfile) -> None:
        """Refresh only the missing tail for an inactive radar market.

        A complete multi-day request on every radar cycle would be both slow and
        wasteful. The overlap minute lets the merge repair an incomplete final
        candle while keeping NQ/ES/GC background data recent enough for alerts.
        """
        with self._lock:
            cache = self._history_cache.get(profile.symbol)
            start = cache.candles[-1].time - timedelta(minutes=2) if cache and cache.candles else None
        if start is None:
            await self._refresh_history(profile, None)
            return
        try:
            loaded = await asyncio.to_thread(self._load_history_since, profile, start)
            self._merge_background_history(profile, loaded)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Databento incremental radar refresh failed for %s", profile.symbol)

    def _merge_background_history(self, profile: InstrumentProfile, loaded: list[Candle]) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            cache = self._history_cache.get(profile.symbol)
            if not cache:
                if loaded:
                    self._store_history(profile, loaded)
                return
            if not loaded:
                cache.loaded_at = now
                return
            merged = {candle.time: candle.model_copy(deep=True) for candle in cache.candles}
            for candle in loaded:
                merged[candle.time] = candle.model_copy(deep=True)
            values = _sanitize_candles(sorted(merged.values(), key=lambda candle: candle.time))[-self.max_candles:]
            if not values:
                cache.loaded_at = now
                return
            self._history_cache[profile.symbol] = _MarketHistoryCache(
                candles=[candle.model_copy(deep=True) for candle in values],
                current_price=values[-1].close,
                raw_symbol=cache.raw_symbol,
                loaded_at=now,
            )

    def cache_status(self, symbol: str) -> dict:
        profile = get_instrument(symbol)
        with self._lock:
            if profile.symbol == self.instrument.symbol and self.candles:
                return {"symbol": profile.symbol, "cached": True, "age_seconds": 0.0}
            cache = self._history_cache.get(profile.symbol)
        age = (datetime.now(timezone.utc) - cache.loaded_at).total_seconds() if cache else None
        return {"symbol": profile.symbol, "cached": cache is not None, "age_seconds": round(age, 1) if age is not None else None}

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
        now = datetime.now(timezone.utc)
        with self._lock:
            cache = self._history_cache.get(self.instrument.symbol)
            cache_age = (now - cache.loaded_at).total_seconds() if cache else None
            last_record_at = self.last_record_at
            last_candle_at = self.last_candle_at or (self.candles[-1].time if self.candles else None)
            record_age = (now - last_record_at).total_seconds() if last_record_at else None
            candle_age = (now - last_candle_at).total_seconds() if last_candle_at else None
            stale_after = max(
                int(settings.databento_live_stale_seconds),
                int(settings.databento_live_watchdog_seconds) * 2,
            )
            market_expected_live = _cme_globex_expected_live(now)
            stale = bool(
                self._started
                and market_expected_live
                and self.stream_state in {"LIVE", "DEGRADED"}
                and record_age is not None
                and record_age > stale_after
            )
            market_closed = bool(
                self._started
                and not market_expected_live
                and record_age is not None
                and record_age > stale_after
            )
            stream_state = "STALE" if stale else "MARKET_CLOSED" if market_closed else self.stream_state
            connected = bool(self.connected and not stale)
            data_fresh = bool(connected and record_age is not None and record_age <= stale_after)
            return {
                "mode": self.mode,
                "data_source": self.data_source,
                "connected": connected,
                "stream_state": stream_state,
                "server_time": now,
                "last_record_at": last_record_at,
                "last_record_age_seconds": round(record_age, 1) if record_age is not None else None,
                "last_candle_at": last_candle_at,
                "last_candle_age_seconds": round(candle_age, 1) if candle_age is not None else None,
                "data_fresh": data_fresh,
                "stale_after_seconds": stale_after,
                "market_expected_live": market_expected_live,
                "reconnect_attempts": self.reconnect_attempts,
                "total_reconnects": self.total_reconnects,
                "next_retry_at": self.next_retry_at,
                "last_disconnect_reason": self.last_disconnect_reason,
                "last_error": self.last_error,
                "symbol": self.instrument.symbol,
                "futures_symbol": self.instrument.futures_continuous,
                "raw_symbol": self.raw_symbol,
                "candle_count": len(self.candles),
                "warming": self.warming,
                "history_cached": self.history_cached,
                "history_ready": bool(self.history_cached and len(self.candles) >= 50),
                "history_source": self.history_source,
                "data_quality": "STALE" if stale else self.data_quality,
                "cache_age_seconds": round(cache_age, 1) if cache_age is not None else None,
                "cached_symbols": sorted(self._history_cache),
                "instrument": self.instrument.public_dict(),
            }



market_data_service = DatabentoMarketDataService() if settings.use_databento else SimulatedMarketDataService()
