import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.core.config import settings
from backend.models.schemas import EngineSnapshot, TradeSetup
from backend.services.market_data import market_data_service
from backend.services.session_service import get_session_status
from backend.services.setup_service import build_candidate_setup
from backend.services.storage_service import storage_service

logger = logging.getLogger(__name__)
TERMINAL = {"TP2_HIT", "STOPPED", "EXPIRED", "INVALIDATED"}


class TradeEngineService:
    def __init__(self):
        self._lock = threading.RLock()
        self._task: asyncio.Task | None = None
        self._current: TradeSetup | None = None
        self._last_terminal: TradeSetup | None = None
        self._last_cycle_at: datetime | None = None
        self._last_processed_candle_time: datetime | None = None
        self._last_error: str | None = None
        self._running = False

    async def start(self) -> None:
        if self._task is None:
            self._running = True
            await self.run_once()
            self._task = asyncio.create_task(self._loop(), name="trade-engine-loop")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(max(1, settings.engine_cycle_seconds))
            await self.run_once()

    async def run_once(self) -> TradeSetup | None:
        try:
            candidate = await asyncio.to_thread(build_candidate_setup)
            candles = market_data_service.snapshot(limit=3)
            if not candles:
                return None
            # Use the most recent closed one-minute candle. The newest bar may still be updating.
            closed = candles[-2] if len(candles) >= 2 else candles[-1]
            with self._lock:
                self._last_cycle_at = datetime.now(timezone.utc)
                self._last_error = None
                if self._current is None or self._current.order_state in TERMINAL:
                    self._current = self._maybe_arm(candidate, closed)
                else:
                    self._current = self._refresh_context(self._current, candidate)
                    if self._last_processed_candle_time is None or closed.time > self._last_processed_candle_time:
                        self._current = self._advance(self._current, candidate, closed)
                if self._last_processed_candle_time is None or closed.time > self._last_processed_candle_time:
                    self._last_processed_candle_time = closed.time
                storage_service.save_setup(self._current, self._result_r(self._current))
                if self._current.order_state in TERMINAL:
                    self._last_terminal = self._current.model_copy(deep=True)
                return self._current.model_copy(deep=True)
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("Trade engine cycle failed")
            return self.current_setup()

    def _maybe_arm(self, candidate: TradeSetup, candle) -> TradeSetup:
        session = get_session_status()
        if not session["can_trade_now"]:
            # Preserve the calculated confidence and every confluence component.
            # Session status is only a separate permission gate for new orders.
            return candidate.model_copy(update={
                "order_state": "PREVIEW_ONLY",
                "actionable": False,
                "status": "MARKET_CLOSED",
            })
        if not candidate.actionable:
            return candidate.model_copy(update={"order_state": "PREVIEW_ONLY", "actionable": False})
        now = datetime.now(timezone.utc)
        armed = candidate.model_copy(deep=True, update={
            "setup_id": str(uuid4()), "timestamp": now,
            "valid_until": now + timedelta(minutes=settings.setup_expiry_minutes),
            "order_state": "WAITING_FOR_LIMIT", "status": "WAITING_FOR_LIMIT",
            "actionable": True, "armed_at": now, "armed_candle_time": candle.time,
            "last_processed_candle_time": candle.time,
        })
        storage_service.transition(armed, "PREVIEW_ONLY", "WAITING_FOR_LIMIT", armed.entry, candle.time, "Setup armed after all mandatory confluences passed.", "positive")
        return armed

    def _refresh_context(self, active: TradeSetup, candidate: TradeSetup) -> TradeSetup:
        fields = {
            "confidence": candidate.confidence, "confidence_components": candidate.confidence_components,
            "confidence_maximums": candidate.confidence_maximums, "signals": candidate.signals,
            "rationale": candidate.rationale, "gex": candidate.gex, "zones": candidate.zones,
            "fib_levels": candidate.fib_levels, "atr": candidate.atr, "vwap": candidate.vwap,
            "standard_deviation_high": candidate.standard_deviation_high,
            "standard_deviation_low": candidate.standard_deviation_low,
            "cluster_score": candidate.cluster_score, "cluster_low": candidate.cluster_low,
            "cluster_high": candidate.cluster_high, "cluster_gex_level": candidate.cluster_gex_level,
            "cluster_gex_type": candidate.cluster_gex_type, "selected_zone_low": candidate.selected_zone_low,
            "selected_zone_high": candidate.selected_zone_high,
            "selected_zone_timeframe": candidate.selected_zone_timeframe,
        }
        return active.model_copy(update=fields)

    def _transition(self, setup: TradeSetup, new_state: str, candle, detail: str, **updates) -> TradeSetup:
        previous = setup.order_state
        now = datetime.now(timezone.utc)
        payload = {"order_state": new_state, "status": new_state, "last_processed_candle_time": candle.time, **updates}
        updated = setup.model_copy(update=payload)
        severity = "positive" if new_state in {"FILLED", "TP1_HIT", "TP2_HIT"} else "negative" if new_state == "STOPPED" else "warning"
        storage_service.transition(updated, previous, new_state, candle.close, candle.time, detail, severity)
        return updated

    def _advance(self, active: TradeSetup, candidate: TradeSetup, candle) -> TradeSetup:
        # Never use the candle that existed before or at the instant the plan was armed.
        if active.armed_candle_time and candle.time <= active.armed_candle_time:
            return active.model_copy(update={"last_processed_candle_time": candle.time})
        now = datetime.now(timezone.utc)
        state = active.order_state
        if state == "WAITING_FOR_LIMIT" and now >= active.valid_until:
            return self._transition(active, "EXPIRED", candle, "The resting limit was not filled before expiry.", actionable=False, closed_at=now, outcome="EXPIRED")
        if state == "WAITING_FOR_LIMIT" and candidate.direction != active.direction and candidate.confidence >= settings.setup_actionable_score:
            return self._transition(active, "INVALIDATED", candle, "A strong opposite-direction setup invalidated the unfilled plan.", actionable=False, closed_at=now, outcome="OPPOSITE_SETUP")
        if state == "WAITING_FOR_LIMIT" and (candidate.confidence < 50 or not candidate.signals.get("gex_alignment") or candidate.cluster_score < .35):
            return self._transition(active, "INVALIDATED", candle, "The original confluence cluster was lost before entry.", actionable=False, closed_at=now, outcome="CONFLUENCE_LOST")

        if state == "WAITING_FOR_LIMIT":
            touched_entry = candle.low <= active.entry <= candle.high
            if not touched_entry:
                return active.model_copy(update={"last_processed_candle_time": candle.time})
            stop_touched = candle.low <= active.stop_loss <= candle.high
            if stop_touched:
                return self._transition(active, "STOPPED", candle, "Entry and stop occurred within the same OHLC candle; conservatively recorded stop-first.", actionable=False, filled_at=now, closed_at=now, outcome="STOPPED_ON_FILL_CANDLE")
            tp2_touched = candle.low <= active.take_profit_2 <= candle.high
            tp1_touched = candle.low <= active.take_profit_1 <= candle.high
            if tp2_touched:
                return self._transition(active, "TP2_HIT", candle, "The fill candle also reached TP2 without touching the stop.", actionable=False, filled_at=now, closed_at=now, outcome="TP2_HIT")
            if tp1_touched:
                return self._transition(active, "TP1_HIT", candle, "The fill candle reached TP1.", filled_at=now, outcome="TP1_HIT_RUNNING")
            return self._transition(active, "FILLED", candle, "The resting limit was filled.", filled_at=now, outcome="OPEN")

        if state in {"FILLED", "TP1_HIT"}:
            stop_touched = candle.low <= active.stop_loss <= candle.high
            tp2_touched = candle.low <= active.take_profit_2 <= candle.high
            tp1_touched = candle.low <= active.take_profit_1 <= candle.high
            if stop_touched and tp2_touched:
                return self._transition(active, "STOPPED", candle, "Stop and TP2 were both inside one candle; conservatively recorded stop-first.", actionable=False, closed_at=now, outcome="AMBIGUOUS_STOP_FIRST")
            if stop_touched:
                return self._transition(active, "STOPPED", candle, "The protective stop was hit.", actionable=False, closed_at=now, outcome="STOPPED")
            if tp2_touched:
                return self._transition(active, "TP2_HIT", candle, "The final target was reached.", actionable=False, closed_at=now, outcome="TP2_HIT")
            if state == "FILLED" and tp1_touched:
                return self._transition(active, "TP1_HIT", candle, "The first target was reached; the remaining position is still tracked.", outcome="TP1_HIT_RUNNING")
        return active.model_copy(update={"last_processed_candle_time": candle.time})

    def _result_r(self, setup: TradeSetup) -> float | None:
        if setup.order_state == "TP2_HIT":
            return setup.tp2_r or setup.risk_reward or 2.0
        if setup.order_state == "STOPPED":
            return -1.0
        if setup.order_state == "EXPIRED" or setup.order_state == "INVALIDATED":
            return 0.0
        return None

    def current_setup(self) -> TradeSetup | None:
        with self._lock:
            return self._current.model_copy(deep=True) if self._current else None

    def reset(self) -> None:
        with self._lock:
            self._current = None

    def snapshot(self) -> EngineSnapshot:
        with self._lock:
            return EngineSnapshot(running=self._running, last_cycle_at=self._last_cycle_at, last_processed_candle_time=self._last_processed_candle_time, current_setup=self._current.model_copy(deep=True) if self._current else None, last_error=self._last_error)


trade_engine_service = TradeEngineService()
