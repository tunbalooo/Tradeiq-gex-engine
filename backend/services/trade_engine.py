import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.core.config import settings
from backend.models.schemas import EngineSnapshot, TradeSetup
from backend.services.instruments import get_instrument
from backend.services.market_data import market_data_service
from backend.services.session_service import get_session_status
from backend.services.setup_service import build_candidate_setup
from backend.services.storage_service import storage_service

logger = logging.getLogger(__name__)
TERMINAL = {"TP2_HIT", "STOPPED", "EXPIRED", "INVALIDATED", "UNCONFIRMED_TOUCH"}
WATCH_MIN_CONFIDENCE = 55.0


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
        self._restored_setup_id: str | None = None
        self._restored_at: datetime | None = None
        # Prevent an expired watch from being recreated every engine cycle.
        # The suppression is cleared only after the market presents a materially
        # different candidate (direction/entry/cluster) or loses watch eligibility.
        self._expired_watch: dict[str, object] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._running = True
            self.restore_from_storage()
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


    def restore_from_storage(self) -> TradeSetup | None:
        """Rehydrate the latest active lifecycle object before the first cycle."""
        with self._lock:
            if self._current is not None:
                return self._current.model_copy(deep=True)
            symbol = market_data_service.symbol
            restored = storage_service.load_active_setup(symbol=symbol)
            if restored is None:
                return None
            self._current = restored
            self._last_processed_candle_time = restored.last_processed_candle_time
            self._restored_setup_id = restored.setup_id
            self._restored_at = self._utcnow()
            logger.info("Restored active TradeIQ setup %s in %s", restored.setup_id, restored.order_state)
            return restored.model_copy(deep=True)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(max(1, settings.engine_cycle_seconds))
            await self.run_once()

    def _utcnow(self) -> datetime:
        """Single clock seam so expiry behaviour is deterministic in tests."""
        return datetime.now(timezone.utc)

    @staticmethod
    def _finite_number(value) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number == number and abs(number) != float("inf") else None

    def _remember_expired_watch(self, watching: TradeSetup) -> None:
        self._expired_watch = {
            "symbol": watching.symbol,
            "direction": watching.direction,
            "entry": self._finite_number(watching.watch_trigger if watching.watch_trigger is not None else watching.entry),
            "cluster_low": self._finite_number(watching.cluster_low),
            "cluster_high": self._finite_number(watching.cluster_high),
            "zone_timeframe": watching.selected_zone_timeframe,
            "expired_at": self._utcnow(),
            "setup_id": watching.setup_id,
        }

    def _same_as_expired_watch(self, candidate: TradeSetup) -> bool:
        expired = self._expired_watch
        if not expired:
            return False
        if candidate.symbol != expired.get("symbol") or candidate.direction != expired.get("direction"):
            self._expired_watch = None
            return False
        if not self._is_watch_candidate(candidate):
            # The old idea fully disappeared. A later reappearance can be treated
            # as a new watch instead of an endlessly renewed copy.
            self._expired_watch = None
            return False

        profile = get_instrument(candidate.symbol)
        atr = max(float(candidate.atr or 0.0), profile.tick_size)
        entry_tolerance = max(profile.tick_size * 4, atr * 0.15)
        old_entry = self._finite_number(expired.get("entry"))
        new_entry = self._finite_number(candidate.entry)
        if old_entry is None or new_entry is None or abs(new_entry - old_entry) > entry_tolerance:
            self._expired_watch = None
            return False

        old_low = self._finite_number(expired.get("cluster_low"))
        old_high = self._finite_number(expired.get("cluster_high"))
        new_low = self._finite_number(candidate.cluster_low)
        new_high = self._finite_number(candidate.cluster_high)
        if all(value is not None for value in (old_low, old_high, new_low, new_high)):
            cluster_tolerance = max(profile.tick_size * 8, atr * 0.25)
            old_mid = (old_low + old_high) / 2
            new_mid = (new_low + new_high) / 2
            if abs(new_mid - old_mid) > cluster_tolerance:
                self._expired_watch = None
                return False

        old_tf = expired.get("zone_timeframe")
        if old_tf and candidate.selected_zone_timeframe and old_tf != candidate.selected_zone_timeframe:
            self._expired_watch = None
            return False
        return True

    async def run_once(self) -> TradeSetup | None:
        try:
            candidate = await asyncio.to_thread(build_candidate_setup)
            candles = market_data_service.snapshot(limit=3)
            if not candles:
                return None
            # Use the most recent closed one-minute candle. The newest bar may still be updating.
            closed = candles[-2] if len(candles) >= 2 else candles[-1]
            with self._lock:
                self._last_cycle_at = self._utcnow()
                self._last_error = None
                if self._current is None or self._current.order_state in TERMINAL:
                    self._current = self._evaluate_candidate(candidate, closed)
                elif self._current.order_state == "PREVIEW_ONLY":
                    # Preview/scanning plans may become a stable WATCHING candidate or
                    # arm after history/session gates are satisfied.
                    refreshed = self._evaluate_candidate(candidate, closed)
                    if refreshed.order_state == "PREVIEW_ONLY":
                        refreshed = refreshed.model_copy(update={
                            "setup_id": self._current.setup_id,
                            "timestamp": self._current.timestamp,
                        })
                    self._current = refreshed
                elif self._current.order_state == "WATCHING":
                    self._current = self._advance_watching(self._current, candidate, closed)
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

    # Legacy readiness payload reference: {"status": "DATA_SYNCING"}
    def _market_gate(self) -> tuple[bool, str | None]:
        market = market_data_service.health()
        if market.get("warming") or (market.get("data_source") == "databento" and not market.get("history_cached", False)):
            return False, "DATA_SYNCING"
        session = get_session_status()
        if not session["can_trade_now"]:
            return False, "MARKET_CLOSED"
        return True, None

    def _is_watch_candidate(self, candidate: TradeSetup) -> bool:
        return bool(
            candidate.entry_valid
            and candidate.direction in {"LONG", "SHORT"}
            and candidate.entry is not None
            and candidate.confidence >= WATCH_MIN_CONFIDENCE
        )

    def _preview(self, candidate: TradeSetup, status: str | None = None) -> TradeSetup:
        return candidate.model_copy(update={
            "order_state": "PREVIEW_ONLY",
            "actionable": False,
            "status": status or candidate.status,
        })

    def _start_watching(self, candidate: TradeSetup, candle, *, setup_id: str | None = None, timestamp: datetime | None = None) -> TradeSetup:
        now = self._utcnow()
        watch_expires_at = now + timedelta(minutes=settings.setup_expiry_minutes)
        self._expired_watch = None
        trigger = self._finite_number(candidate.entry)
        transition_reason = (
            f"TradeIQ is monitoring a {candidate.direction.lower()} candidate near {trigger:,.2f}; "
            "the full limit plan is not armed because one or more mandatory confirmations are still missing."
        )
        watching = candidate.model_copy(deep=True, update={
            "setup_id": setup_id or str(uuid4()),
            "timestamp": timestamp or now,
            "valid_until": watch_expires_at,
            "watch_started_at": now,
            "watch_expires_at": watch_expires_at,
            "watch_trigger": trigger,
            "order_state": "WATCHING",
            "status": f"MONITORING_{candidate.direction}",
            "actionable": False,
            "armed_at": None,
            "armed_candle_time": None,
            # A monitoring state is deliberately not an executable plan. Keeping
            # entry/SL/TP empty prevents the UI or a downstream integration from
            # treating the trigger as a resting limit before confirmation.
            "entry": None,
            "stop_loss": None,
            "take_profit_1": None,
            "take_profit_2": None,
            "risk_reward": None,
            "tp1_r": None,
            "tp2_r": None,
            "target_sources": {},
            "last_transition_from": "PREVIEW_ONLY",
            "last_transition_to": "WATCHING",
            "last_transition_reason": transition_reason,
            "last_transition_at": now,
            "last_transition_price": trigger,
            "last_processed_candle_time": candle.time,
        })
        storage_service.transition(
            watching, "PREVIEW_ONLY", "WATCHING", trigger, candle.time,
            transition_reason,
            "warning",
        )
        return watching

    def _arm_candidate(
        self, candidate: TradeSetup, candle, *, previous_state: str = "PREVIEW_ONLY",
        setup_id: str | None = None, timestamp: datetime | None = None,
        watch_started_at: datetime | None = None, watch_expires_at: datetime | None = None,
    ) -> TradeSetup:
        now = self._utcnow()
        transition_reason = (
            "The deterministic engine received the remaining mandatory confirmations. "
            "The limit entry, protective stop, TP1, TP2 and risk box are now complete and locked."
        )
        armed = candidate.model_copy(deep=True, update={
            "setup_id": setup_id or str(uuid4()),
            "timestamp": timestamp or now,
            "valid_until": now + timedelta(minutes=settings.setup_expiry_minutes),
            "watch_started_at": watch_started_at,
            "watch_expires_at": watch_expires_at,
            "order_state": "WAITING_FOR_LIMIT",
            "status": "WAITING_FOR_LIMIT",
            "actionable": True,
            "armed_at": now,
            "armed_candle_time": candle.time,
            "last_transition_from": previous_state,
            "last_transition_to": "WAITING_FOR_LIMIT",
            "last_transition_reason": transition_reason,
            "last_transition_at": now,
            "last_transition_price": armed_entry if (armed_entry := self._finite_number(candidate.entry)) is not None else self._finite_number(candle.close),
            "last_processed_candle_time": candle.time,
            "initial_stop_loss": candidate.stop_loss,
            "active_stop_loss": candidate.stop_loss,
            "management_state": "LIMIT_ARMED",
            "partial_exit_percent": settings.partial_exit_percent,
            "runner_active": False,
            "management_actions": [
                {"at": now.isoformat(), "action": "LIMIT_ARMED", "detail": "Entry, initial stop and targets locked."}
            ],
        })
        storage_service.transition(
            armed, previous_state, "WAITING_FOR_LIMIT", armed.entry, candle.time,
            transition_reason,
            "positive",
        )
        return armed

    def _evaluate_candidate(self, candidate: TradeSetup, candle) -> TradeSetup:
        can_trade, gate_status = self._market_gate()
        if not can_trade:
            return self._preview(candidate, gate_status)
        if self._same_as_expired_watch(candidate):
            return self._preview(candidate, "WATCH_EXPIRED")
        if candidate.actionable:
            return self._arm_candidate(candidate, candle)
        if self._is_watch_candidate(candidate):
            return self._start_watching(candidate, candle)
        return self._preview(candidate)

    # Backward-compatible internal name used by earlier tests and integrations.
    def _maybe_arm(self, candidate: TradeSetup, candle) -> TradeSetup:
        return self._evaluate_candidate(candidate, candle)

    def _advance_watching(self, watching: TradeSetup, candidate: TradeSetup, candle) -> TradeSetup:
        can_trade, gate_status = self._market_gate()
        if not can_trade:
            now = self._utcnow()
            reason = (
                "Monitoring ended because live execution is unavailable while market data is syncing."
                if gate_status == "DATA_SYNCING"
                else "Monitoring ended because the session gate is closed; no limit order was armed."
            )
            preview = self._preview(candidate, gate_status)
            updated = preview.model_copy(update={
                "setup_id": watching.setup_id,
                "timestamp": watching.timestamp,
                "last_transition_from": "WATCHING",
                "last_transition_to": "PREVIEW_ONLY",
                "last_transition_reason": reason,
                "last_transition_at": now,
                "last_transition_price": self._finite_number(candle.close),
                "last_processed_candle_time": candle.time,
            })
            storage_service.transition(updated, "WATCHING", "PREVIEW_ONLY", candle.close, candle.time, reason, "warning")
            return updated

        same_direction = candidate.direction == watching.direction
        now = self._utcnow()
        watch_expires_at = watching.watch_expires_at or watching.valid_until
        # Expiry is checked before confirmation. A candidate cannot be armed after
        # its original watch deadline merely because the next engine cycle arrived late.
        if now >= watch_expires_at:
            self._remember_expired_watch(watching)
            return self._transition(
                watching, "EXPIRED", candle,
                "The watched candidate expired without final confirmation. A new watch requires a materially new setup.",
                actionable=False, closed_at=now, outcome="WATCH_EXPIRED",
            )

        # A developing thesis may rotate to a stronger secondary execution model
        # without being discarded. The lifecycle and exact switch reason remain
        # visible to Claude and the setup timeline.
        model_changed = bool(
            same_direction
            and candidate.primary_entry_model
            and candidate.primary_entry_model != watching.primary_entry_model
            and self._is_watch_candidate(candidate)
        )
        if model_changed and not candidate.actionable:
            new_trigger = self._finite_number(candidate.entry)
            if new_trigger is not None:
                reason = (
                    f"Primary entry model changed from {watching.primary_entry_model or 'unclassified'} "
                    f"to {candidate.primary_entry_model} at {candidate.primary_model_score:.1f}%. "
                    "TradeIQ is monitoring the stronger secondary opportunity; no order is armed."
                )
                switched = self._refresh_context(watching, candidate).model_copy(update={
                    "primary_entry_model": candidate.primary_entry_model,
                    "primary_entry_model_key": candidate.primary_entry_model_key,
                    "primary_model_score": candidate.primary_model_score,
                    "entry_model_scores": candidate.entry_model_scores,
                    "alternative_entry_models": candidate.alternative_entry_models,
                    "model_selection_reason": candidate.model_selection_reason,
                    "model_selected_at": now,
                    "model_switch_count": watching.model_switch_count + 1,
                    "watch_trigger": new_trigger,
                    "last_transition_from": "WATCHING",
                    "last_transition_to": "WATCHING",
                    "last_transition_reason": reason,
                    "last_transition_at": now,
                    "last_transition_price": new_trigger,
                    "last_processed_candle_time": candle.time,
                })
                storage_service.transition(switched, "WATCHING", "WATCHING", new_trigger, candle.time, reason, "info")
                return switched

        if candidate.actionable and same_direction:
            return self._arm_candidate(
                candidate, candle, previous_state="WATCHING",
                setup_id=watching.setup_id, timestamp=watching.timestamp,
                watch_started_at=watching.watch_started_at or watching.timestamp,
                watch_expires_at=watch_expires_at,
            )

        # A monitored trigger is not a resting order. If price reaches it before
        # the deterministic engine confirms the full plan, record an unconfirmed
        # touch rather than pretending that a fill occurred or showing stale TP/SL.
        trigger = self._finite_number(watching.watch_trigger)
        new_closed_candle = watching.last_processed_candle_time is None or candle.time > watching.last_processed_candle_time
        if new_closed_candle and trigger is not None and candle.low <= trigger <= candle.high:
            self._remember_expired_watch(watching)
            return self._transition(
                watching, "UNCONFIRMED_TOUCH", candle,
                "Price touched the monitoring trigger before the setup was confirmed. No order was armed and no fill is recorded.",
                actionable=False, closed_at=now, outcome="UNCONFIRMED_TOUCH",
            )

        if not same_direction or not self._is_watch_candidate(candidate):
            replacement = self._evaluate_candidate(candidate, candle)
            if replacement.order_state == "PREVIEW_ONLY":
                now = self._utcnow()
                reason = (
                    "The monitoring candidate was cancelled because its direction changed before confirmation."
                    if not same_direction
                    else "The monitoring candidate was cancelled because its required confirmations weakened before a limit plan was armed."
                )
                replacement = replacement.model_copy(update={
                    "setup_id": watching.setup_id,
                    "timestamp": watching.timestamp,
                    "last_transition_from": "WATCHING",
                    "last_transition_to": "PREVIEW_ONLY",
                    "last_transition_reason": reason,
                    "last_transition_at": now,
                    "last_transition_price": self._finite_number(candle.close),
                })
                storage_service.transition(
                    replacement, "WATCHING", "PREVIEW_ONLY", candle.close, candle.time,
                    reason,
                    "warning",
                )
            return replacement

        # Keep the original watched direction and entry fixed. Only market context,
        # confidence and confluence diagnostics are refreshed while confirmation develops.
        refreshed = self._refresh_context(watching, candidate)
        return refreshed.model_copy(update={
            "primary_entry_model": watching.primary_entry_model or candidate.primary_entry_model,
            "primary_entry_model_key": watching.primary_entry_model_key or candidate.primary_entry_model_key,
            "primary_model_score": candidate.primary_model_score,
            "entry_model_scores": candidate.entry_model_scores,
            "alternative_entry_models": candidate.alternative_entry_models,
            "model_selection_reason": candidate.model_selection_reason,
            "confidence_grade": candidate.confidence_grade,
            "institutional_confidence_components": candidate.institutional_confidence_components,
            "institutional_confidence_maximums": candidate.institutional_confidence_maximums,
            "status": f"MONITORING_{watching.direction}",
            "order_state": "WATCHING",
            "actionable": False,
            "watch_started_at": watching.watch_started_at or watching.timestamp,
            "watch_expires_at": watch_expires_at,
            "watch_trigger": watching.watch_trigger,
            "valid_until": watch_expires_at,
            "last_processed_candle_time": candle.time,
        })

    def _refresh_context(self, active: TradeSetup, candidate: TradeSetup) -> TradeSetup:
        fields = {
            "symbol": candidate.symbol,
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
            "confidence_grade": candidate.confidence_grade,
            "institutional_confidence_components": candidate.institutional_confidence_components,
            "institutional_confidence_maximums": candidate.institutional_confidence_maximums,
        }
        return active.model_copy(update=fields)

    def _transition(self, setup: TradeSetup, new_state: str, candle, detail: str, **updates) -> TradeSetup:
        previous = setup.order_state
        now = self._utcnow()
        payload = {
            "order_state": new_state,
            "status": new_state,
            "last_transition_from": previous,
            "last_transition_to": new_state,
            "last_transition_reason": detail,
            "last_transition_at": now,
            "last_transition_price": self._finite_number(candle.close),
            "last_processed_candle_time": candle.time,
            **updates,
        }
        updated = setup.model_copy(update=payload)
        severity = "positive" if new_state in {"FILLED", "TP1_HIT", "TP2_HIT"} else "negative" if new_state == "STOPPED" else "warning"
        storage_service.transition(updated, previous, new_state, candle.close, candle.time, detail, severity)
        return updated

    def _update_excursions(self, active: TradeSetup, candle) -> TradeSetup:
        if active.entry is None or active.order_state not in {"FILLED", "TP1_HIT"}:
            return active
        if active.direction == "LONG":
            favorable = max(0.0, float(candle.high) - active.entry)
            adverse = max(0.0, active.entry - float(candle.low))
        else:
            favorable = max(0.0, active.entry - float(candle.low))
            adverse = max(0.0, float(candle.high) - active.entry)
        return active.model_copy(update={
            "max_favorable_excursion_points": round(max(active.max_favorable_excursion_points, favorable), 2),
            "max_adverse_excursion_points": round(max(active.max_adverse_excursion_points, adverse), 2),
        })

    def _tp1_management_updates(self, active: TradeSetup, now: datetime) -> dict:
        actions = list(active.management_actions)
        actions.append({
            "at": now.isoformat(),
            "action": "TP1_HIT",
            "detail": f"Secured {settings.partial_exit_percent:.0f}% at TP1; runner remains active.",
        })
        updates = {
            "tp1_hit_at": now,
            "management_state": "TP1_SECURED",
            "runner_active": True,
            "partial_exit_percent": settings.partial_exit_percent,
            "management_actions": actions,
        }
        if settings.move_stop_to_breakeven_after_tp1 and active.entry is not None:
            actions.append({
                "at": now.isoformat(),
                "action": "MOVE_TO_BREAKEVEN",
                "detail": "Runner stop advanced to the locked entry after TP1.",
            })
            updates.update({
                "active_stop_loss": active.entry,
                "breakeven_at": now,
                "management_actions": actions,
            })
        return updates

    def _advance(self, active: TradeSetup, candidate: TradeSetup, candle) -> TradeSetup:
        # Never use the candle that existed before or at the instant the plan was armed.
        if active.armed_candle_time and candle.time <= active.armed_candle_time:
            return active.model_copy(update={"last_processed_candle_time": candle.time})
        now = self._utcnow()
        state = active.order_state
        active = self._update_excursions(active, candle)
        if state == "WAITING_FOR_LIMIT" and now >= active.valid_until:
            return self._transition(active, "EXPIRED", candle, "The resting limit was not filled before expiry.", actionable=False, closed_at=now, outcome="EXPIRED")
        if state == "WAITING_FOR_LIMIT":
            touched_entry = candle.low <= active.entry <= candle.high
            # A locked resting limit is evaluated before fresh context can cancel it.
            # This prevents the exact fill candle from being mislabeled INVALIDATED
            # merely because confidence/GEX/cluster values changed after price arrived.
            if not touched_entry:
                if candidate.direction != active.direction and candidate.confidence >= settings.setup_actionable_score:
                    return self._transition(active, "INVALIDATED", candle, "A strong opposite-direction setup invalidated the unfilled plan.", actionable=False, closed_at=now, outcome="OPPOSITE_SETUP")
                if candidate.confidence < 50 or not candidate.signals.get("gex_alignment") or candidate.cluster_score < .35:
                    return self._transition(active, "INVALIDATED", candle, "The original confluence cluster was lost before entry.", actionable=False, closed_at=now, outcome="CONFLUENCE_LOST")
                return active.model_copy(update={"last_processed_candle_time": candle.time})
            stop_touched = candle.low <= active.stop_loss <= candle.high
            if stop_touched:
                return self._transition(active, "STOPPED", candle, "Entry and stop occurred within the same OHLC candle; conservatively recorded stop-first.", actionable=False, filled_at=now, closed_at=now, outcome="STOPPED_ON_FILL_CANDLE", management_state="STOPPED", runner_active=False)
            tp2_touched = candle.low <= active.take_profit_2 <= candle.high
            tp1_touched = candle.low <= active.take_profit_1 <= candle.high
            if tp2_touched:
                return self._transition(active, "TP2_HIT", candle, "The fill candle also reached TP2 without touching the stop.", actionable=False, filled_at=now, closed_at=now, outcome="TP2_HIT", management_state="COMPLETE", runner_active=False)
            if tp1_touched:
                return self._transition(active, "TP1_HIT", candle, "The fill candle reached TP1; partial profit was secured and the runner stop advanced according to policy.", filled_at=now, outcome="TP1_HIT_RUNNING", **self._tp1_management_updates(active, now))
            actions = list(active.management_actions) + [{"at": now.isoformat(), "action": "FILLED", "detail": "Locked limit filled; risk management is active."}]
            return self._transition(active, "FILLED", candle, "The resting limit was filled.", filled_at=now, outcome="OPEN", management_state="POSITION_ACTIVE", runner_active=True, active_stop_loss=active.active_stop_loss or active.stop_loss, management_actions=actions)

        if state in {"FILLED", "TP1_HIT"}:
            stop_reference = active.active_stop_loss if active.active_stop_loss is not None else active.stop_loss
            stop_touched = stop_reference is not None and candle.low <= stop_reference <= candle.high
            tp2_touched = candle.low <= active.take_profit_2 <= candle.high
            tp1_touched = candle.low <= active.take_profit_1 <= candle.high
            if stop_touched and tp2_touched:
                return self._transition(active, "STOPPED", candle, "Active stop and TP2 were both inside one candle; conservatively recorded stop-first.", actionable=False, closed_at=now, outcome="AMBIGUOUS_STOP_FIRST", management_state="STOPPED", runner_active=False)
            if stop_touched:
                at_breakeven = state == "TP1_HIT" and active.entry is not None and abs(float(stop_reference) - active.entry) < 1e-9
                detail = "The runner returned to the break-even stop after TP1." if at_breakeven else "The active protective stop was hit."
                outcome = "BREAKEVEN_AFTER_TP1" if at_breakeven else "STOPPED"
                return self._transition(active, "STOPPED", candle, detail, actionable=False, closed_at=now, outcome=outcome, management_state="COMPLETE" if at_breakeven else "STOPPED", runner_active=False)
            if tp2_touched:
                return self._transition(active, "TP2_HIT", candle, "The final target was reached.", actionable=False, closed_at=now, outcome="TP2_HIT", management_state="COMPLETE", runner_active=False)
            if state == "FILLED" and tp1_touched:
                return self._transition(active, "TP1_HIT", candle, "The first target was reached; partial profit was secured and the runner is still tracked.", outcome="TP1_HIT_RUNNING", **self._tp1_management_updates(active, now))
        return active.model_copy(update={"last_processed_candle_time": candle.time})

    def _result_r(self, setup: TradeSetup) -> float | None:
        if setup.order_state == "TP2_HIT":
            return setup.tp2_r or setup.risk_reward or 2.0
        if setup.order_state == "STOPPED":
            if setup.outcome == "BREAKEVEN_AFTER_TP1":
                secured = (setup.tp1_r or 1.0) * (setup.partial_exit_percent / 100.0)
                return round(secured, 2)
            return -1.0
        if setup.order_state in {"EXPIRED", "INVALIDATED", "UNCONFIRMED_TOUCH"}:
            return 0.0
        return None

    def current_setup(self) -> TradeSetup | None:
        with self._lock:
            return self._current.model_copy(deep=True) if self._current else None

    def reset(self) -> None:
        with self._lock:
            self._current = None
            self._last_processed_candle_time = None
            self._expired_watch = None
            self._restored_setup_id = None
            self._restored_at = None

    def reset_for_symbol(self, symbol: str) -> None:
        with self._lock:
            self._current = None
            self._last_terminal = None
            self._last_processed_candle_time = None
            self._last_error = None
            self._expired_watch = None
            self._restored_setup_id = None
            self._restored_at = None

    def snapshot(self) -> EngineSnapshot:
        with self._lock:
            return EngineSnapshot(
                running=self._running,
                last_cycle_at=self._last_cycle_at,
                last_processed_candle_time=self._last_processed_candle_time,
                current_setup=self._current.model_copy(deep=True) if self._current else None,
                last_error=self._last_error,
                restored_setup_id=self._restored_setup_id,
                restored_at=self._restored_at,
            )


trade_engine_service = TradeEngineService()
