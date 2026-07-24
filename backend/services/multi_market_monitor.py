import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone

from backend.core.config import settings
from backend.models.schemas import MarketOpportunity
from backend.services.instruments import get_instrument, instrument_registry, normalize_symbol
from backend.services.market_data import market_data_service
from backend.services.setup_service import build_candidate_setup
from backend.services.storage_service import storage_service

logger = logging.getLogger(__name__)


class MultiMarketMonitorService:
    """Read-only background scanner for markets that are not on the chart.

    It deliberately does not own trades, orders, stops or lifecycle state. Its
    only job is to surface a qualified developing opportunity so the trader can
    open that instrument and let the active TradeIQ engine validate it using the
    live market/GEX context.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_scan_at: datetime | None = None
        self._last_error: str | None = None
        self._opportunities: dict[str, MarketOpportunity] = {}
        self._last_alert_at: dict[tuple, datetime] = {}

    @property
    def symbols(self) -> list[str]:
        values: list[str] = []
        for raw in str(settings.multi_market_symbols or "NQ,ES,GC").split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                symbol = normalize_symbol(raw)
            except ValueError:
                logger.warning("Ignoring unsupported radar symbol %s", raw)
                continue
            if symbol not in values:
                values.append(symbol)
        return values or ["NQ", "ES", "GC"]

    async def start(self) -> None:
        if not settings.multi_market_alerts_enabled or self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="tradeiq-multi-market-radar")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(1.0)
        while True:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("Multi-market radar cycle failed")
            await asyncio.sleep(max(15, int(settings.multi_market_scan_seconds)))

    async def scan_once(self, symbols: list[str] | None = None) -> list[MarketOpportunity]:
        requested = symbols or self.symbols
        now = datetime.now(timezone.utc)
        results: dict[str, MarketOpportunity] = {}
        errors: list[str] = []

        for raw_symbol in requested:
            try:
                symbol = normalize_symbol(raw_symbol)
                opportunity = await self._scan_symbol(symbol, now)
                results[symbol] = opportunity
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                errors.append(f"{raw_symbol}: {exc}")
                logger.exception("Unable to scan %s in market radar", raw_symbol)
                profile = get_instrument(raw_symbol)
                results[profile.symbol] = MarketOpportunity(
                    opportunity_id=f"{profile.symbol}-syncing",
                    symbol=profile.symbol,
                    display_symbol=profile.display_symbol,
                    direction="NONE",
                    status="SYNCING",
                    reason="Background history is still syncing.",
                    detected_at=now,
                    active_market=profile.symbol == instrument_registry.active.symbol,
                    missing_gates=["scanner error"],
                    alertable=False,
                )

        with self._lock:
            self._opportunities.update(results)
            self._last_scan_at = now
            self._last_error = "; ".join(errors) if errors else None
        return self.snapshot()

    async def _scan_symbol(self, symbol: str, now: datetime) -> MarketOpportunity:
        profile = get_instrument(symbol)
        candles = await market_data_service.refresh_symbol_cache(profile.symbol)
        if len(candles) < 100:
            return MarketOpportunity(
                opportunity_id=f"{profile.symbol}-syncing",
                symbol=profile.symbol,
                display_symbol=profile.display_symbol,
                direction="NONE",
                status="SYNCING",
                reason="Waiting for enough historical candles to score the market.",
                detected_at=now,
                candle_time=candles[-1].time if candles else None,
                active_market=profile.symbol == instrument_registry.active.symbol,
                current_price=candles[-1].close if candles else None,
                missing_gates=["historical candles"],
                alertable=False,
            )

        candidate = await asyncio.to_thread(
            build_candidate_setup,
            candles,
            profile,
            None,
        )
        latest = candles[-1]
        data_age = max(0.0, (now - latest.time).total_seconds())
        model_score = float(candidate.primary_model_score or 0.0)
        confidence = float(candidate.confidence or 0.0)
        data_is_fresh = data_age <= float(settings.multi_market_max_data_age_seconds)
        missing_gates: list[str] = []
        if not data_is_fresh:
            missing_gates.append("fresh market data")
        if candidate.direction not in {"LONG", "SHORT"}:
            missing_gates.append("direction")
        if not candidate.primary_entry_model:
            missing_gates.append("entry model")
        if not candidate.entry_valid:
            missing_gates.append("entry confirmation")
        if model_score < float(settings.multi_market_min_model_score):
            missing_gates.append(f"model score {settings.multi_market_min_model_score:.0f}%")
        if confidence < float(settings.multi_market_min_confidence):
            missing_gates.append(f"confidence {settings.multi_market_min_confidence:.0f}%")
        qualified = not missing_gates
        active_market = profile.symbol == instrument_registry.active.symbol
        watch_price = candidate.signals.get("selected_model_trigger") if candidate.signals else None
        if watch_price is None:
            watch_price = candidate.entry
        invalidation = candidate.signals.get("selected_model_invalidation") if candidate.signals else None
        if invalidation is None:
            invalidation = candidate.stop_loss
        reason = candidate.model_selection_reason or next(iter(candidate.rationale or []), "No qualified model yet.")
        if not data_is_fresh:
            reason = f"Market data is {data_age:.0f}s old. The radar will not alert until a fresh candle is available."
        elif missing_gates:
            reason = f"{reason} Waiting on: {', '.join(missing_gates)}."
        has_developing_model = bool(
            candidate.direction in {"LONG", "SHORT"}
            and candidate.primary_entry_model
        )
        # Legacy v3.0.4 status expression retained for regression documentation:
        # status = "SETUP_FORMING" if qualified else "STALE_DATA"
        status = (
            "SETUP_FORMING"
            if qualified
            else "STALE_DATA"
            if not data_is_fresh
            else "DEVELOPING"
            if has_developing_model
            else "SCANNING"
        )
        price_token = round(float(watch_price), profile.price_precision) if watch_price is not None else "none"
        model_key = candidate.primary_entry_model_key or "none"
        opportunity_id = f"{profile.symbol}:{candidate.direction}:{model_key}:{price_token}"
        opportunity = MarketOpportunity(
            opportunity_id=opportunity_id,
            symbol=profile.symbol,
            display_symbol=profile.display_symbol,
            direction=candidate.direction,
            model=candidate.primary_entry_model,
            model_key=candidate.primary_entry_model_key,
            model_score=round(model_score, 1),
            confidence=round(confidence, 1),
            grade=candidate.confidence_grade,
            watch_price=watch_price,
            invalidation_price=invalidation,
            status=status,
            reason=reason,
            detected_at=now,
            candle_time=latest.time,
            data_age_seconds=round(data_age, 1),
            data_source="active-live" if active_market else "cached-history",
            gex_source=candidate.gex.source_label or candidate.gex.source,
            active_market=active_market,
            qualified=qualified,
            entry_valid=bool(candidate.entry_valid),
            current_price=latest.close,
            missing_gates=missing_gates,
            alertable=qualified and not active_market,
        )
        if opportunity.alertable:
            self._maybe_emit_alert(opportunity, now)
        return opportunity

    def _maybe_emit_alert(self, opportunity: MarketOpportunity, now: datetime) -> None:
        profile = get_instrument(opportunity.symbol)
        price_bucket = (
            round(float(opportunity.watch_price) / max(profile.tick_size * 4, profile.tick_size))
            if opportunity.watch_price is not None
            else None
        )
        signature = (opportunity.symbol, opportunity.direction, opportunity.model_key, price_bucket)
        cooldown = timedelta(minutes=max(1, int(settings.multi_market_alert_cooldown_minutes)))
        with self._lock:
            previous = self._last_alert_at.get(signature)
            if previous and now - previous < cooldown:
                return
            self._last_alert_at[signature] = now

        watch = f" near {opportunity.watch_price:,.{profile.price_precision}f}" if opportunity.watch_price is not None else ""
        title = f"{opportunity.symbol} {opportunity.direction} setup forming"
        detail = (
            f"{opportunity.model or 'Institutional model'} scored {opportunity.model_score:.0f}%{watch}. "
            f"Open {opportunity.symbol} to validate live GEX, confirmation and risk before arming an order."
        )
        severity = "positive" if opportunity.direction == "LONG" else "negative"
        storage_service.save_alert(title=title, detail=detail, severity=severity)

    def snapshot(self) -> list[MarketOpportunity]:
        with self._lock:
            items = [item.model_copy(deep=True) for item in self._opportunities.values()]
        order = {symbol: index for index, symbol in enumerate(self.symbols)}
        return sorted(items, key=lambda item: (order.get(item.symbol, 999), -item.model_score))

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": settings.multi_market_alerts_enabled,
                "running": self._running,
                "symbols": self.symbols,
                "scan_seconds": settings.multi_market_scan_seconds,
                "last_scan_at": self._last_scan_at,
                "last_error": self._last_error,
                "opportunity_count": len(self._opportunities),
                "qualified_count": sum(1 for item in self._opportunities.values() if item.qualified),
                "developing_count": sum(1 for item in self._opportunities.values() if item.status == "DEVELOPING"),
                "alertable_count": sum(1 for item in self._opportunities.values() if item.alertable),
                "cache": [market_data_service.cache_status(symbol) for symbol in self.symbols],
            }


multi_market_monitor_service = MultiMarketMonitorService()
