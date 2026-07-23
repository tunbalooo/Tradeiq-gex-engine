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
WATCH_MIN_CONFIDENCE = 35.0


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
        self._pending_candidate_signature: tuple | None = None
        self._pending_candidate_count = 0
        self._pending_candidate_candle_time: datetime | None = None
        # A terminal thesis is not allowed to respawn from timer/polling refreshes.
        # The fingerprint includes the trigger model, location bucket and latest
        # structure-event key, so a genuinely new MSS/sweep/displacement may trade.
        self._terminal_thesis_locks: dict[str, dict[str, object]] = {}

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
        """Rehydrate active lifecycle state and terminal same-thesis locks."""
        with self._lock:
            if self._current is not None:
                return self._current.model_copy(deep=True)
            symbol = market_data_service.symbol
            cutoff = self._utcnow() - timedelta(minutes=max(1, settings.thesis_lock_max_minutes))
            for item in storage_service.recent_terminal_theses(symbol=symbol, limit=40):
                locked_at = item.get("locked_at")
                if not isinstance(locked_at, datetime) or locked_at < cutoff:
                    continue
                fingerprint = str(item.get("fingerprint") or "").strip()
                if fingerprint:
                    self._terminal_thesis_locks[fingerprint] = {
                        key: value for key, value in item.items() if key != "fingerprint"
                    }
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

    @staticmethod
    def _observation(candle) -> dict[str, object]:
        return {
            "candle_time": candle.time,
            "low": float(candle.low),
            "high": float(candle.high),
            "close": float(candle.close),
        }

    @staticmethod
    def _level_touched_after(
        level: float | None,
        candle,
        *,
        observed_candle_time: datetime | None,
        observed_low: float | None,
        observed_high: float | None,
        observed_close: float | None,
    ) -> bool:
        """Detect a level only after the engine began observing that lifecycle state.

        A live OHLC candle contains price movement from before a watch or order was
        created. Treating the whole range as new produced retrospective watch touches
        and fills. On the same live candle, a level now qualifies only when it was not
        present in the previous observed range or the latest price crossed it. A new
        candle can use its full range because it opened after the prior observation.
        """
        if level is None:
            return False
        level = float(level)
        current_low = float(candle.low)
        current_high = float(candle.high)
        current_close = float(candle.close)
        current_contains = current_low <= level <= current_high
        if observed_candle_time is None:
            return current_contains
        if candle.time > observed_candle_time:
            return current_contains
        if candle.time < observed_candle_time:
            return False
        prior_contains = bool(
            observed_low is not None and observed_high is not None
            and float(observed_low) <= level <= float(observed_high)
        )
        crossed_by_latest_price = bool(
            observed_close is not None
            and min(float(observed_close), current_close) <= level <= max(float(observed_close), current_close)
            and float(observed_close) != current_close
        )
        return bool((current_contains and not prior_contains) or crossed_by_latest_price)

    @classmethod
    def _watch_observation_updates(cls, candle) -> dict[str, object]:
        observed = cls._observation(candle)
        return {
            "watch_observed_candle_time": observed["candle_time"],
            "watch_observed_low": observed["low"],
            "watch_observed_high": observed["high"],
            "watch_observed_close": observed["close"],
        }

    @classmethod
    def _execution_observation_updates(cls, candle) -> dict[str, object]:
        observed = cls._observation(candle)
        return {
            "execution_observed_candle_time": observed["candle_time"],
            "execution_observed_low": observed["low"],
            "execution_observed_high": observed["high"],
            "execution_observed_close": observed["close"],
        }

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

    def _prune_terminal_thesis_locks(self) -> None:
        cutoff = self._utcnow() - timedelta(minutes=max(1, settings.thesis_lock_max_minutes))
        self._terminal_thesis_locks = {
            key: value for key, value in self._terminal_thesis_locks.items()
            if isinstance(value.get("locked_at"), datetime) and value["locked_at"] >= cutoff
        }

    def _remember_terminal_thesis(self, setup: TradeSetup) -> None:
        fingerprint = str(setup.thesis_fingerprint or "").strip()
        if not fingerprint:
            return
        self._prune_terminal_thesis_locks()
        self._terminal_thesis_locks[fingerprint] = {
            "locked_at": self._utcnow(),
            "state": setup.order_state,
            "outcome": setup.outcome,
            "setup_id": setup.setup_id,
            "structure_event_key": setup.structure_event_key,
            "direction": setup.direction,
            "trigger_model": setup.trigger_entry_model or setup.primary_entry_model,
            "entry": self._finite_number(setup.watch_trigger if setup.watch_trigger is not None else setup.entry),
            "cluster_low": self._finite_number(setup.cluster_low),
            "cluster_high": self._finite_number(setup.cluster_high),
        }

    def _terminal_thesis_block_reason(self, candidate: TradeSetup) -> str | None:
        fingerprint = str(candidate.thesis_fingerprint or "").strip()
        if not fingerprint:
            return None
        self._prune_terminal_thesis_locks()
        locked = self._terminal_thesis_locks.get(fingerprint)
        if not locked:
            return None
        # Defensive location check for restored/legacy candidates whose fingerprint
        # may have been copied before their entry was materially changed.
        profile = get_instrument(candidate.symbol)
        tolerance = max(profile.tick_size * 8, float(candidate.atr or profile.tick_size) * 0.25)
        old_entry = self._finite_number(locked.get("entry"))
        new_entry = self._finite_number(candidate.entry)
        if old_entry is not None and new_entry is not None and abs(old_entry - new_entry) > tolerance:
            self._terminal_thesis_locks.pop(fingerprint, None)
            return None
        state = str(locked.get("state") or "terminal state").replace("_", " ").lower()
        model = str(locked.get("trigger_model") or candidate.trigger_entry_model or "setup")
        return (
            f"Same-thesis lock: this {candidate.direction.lower()} {model} at the same location "
            f"and structure event already ended in {state}. TradeIQ requires a new sweep, "
            "structure shift, displacement, or materially new cluster before another entry."
        )

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
            # Closed candles drive deterministic model confirmation. The newest live
            # candle drives watch touches, limit fills, stops and targets so the UI
            # reacts when price actually trades a level instead of waiting for bar close.
            closed = candles[-2] if len(candles) >= 2 else candles[-1]
            live = candles[-1]
            with self._lock:
                self._last_cycle_at = self._utcnow()
                self._last_error = None
                if self._current is None or self._current.order_state in TERMINAL:
                    self._current = self._evaluate_candidate(candidate, closed, live)
                elif self._current.order_state == "PREVIEW_ONLY":
                    # Preview/scanning plans may become a stable WATCHING candidate or
                    # arm after history/session gates are satisfied.
                    refreshed = self._evaluate_candidate(candidate, closed, live)
                    if refreshed.order_state == "PREVIEW_ONLY":
                        refreshed = refreshed.model_copy(update={
                            "setup_id": self._current.setup_id,
                            "timestamp": self._current.timestamp,
                        })
                    self._current = refreshed
                elif self._current.order_state == "WATCHING":
                    self._current = self._advance_watching(self._current, candidate, closed, live)
                else:
                    self._current = self._refresh_context(self._current, candidate)
                    self._current = self._advance(self._current, candidate, live)
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

    def _primary_model_eligible(self, candidate: TradeSetup) -> bool:
        if candidate.primary_entry_model_key == "INSTITUTIONAL_CONFLUENCE_CLUSTER":
            return bool(candidate.composite_cluster_eligible)
        return any(
            item.key == candidate.primary_entry_model_key and item.eligible
            for item in candidate.entry_model_scores
        )

    def _primary_model_invalidation(self, candidate: TradeSetup) -> float | None:
        trigger = self._finite_number(candidate.entry)
        values: list[float | None] = []
        for item in candidate.entry_model_scores:
            if item.key == candidate.primary_entry_model_key:
                values.append(self._finite_number(item.invalidation_price))
                break
        values.extend([
            self._finite_number(candidate.signals.get("selected_model_invalidation")),
            self._finite_number(candidate.stop_loss),
        ])
        for value in values:
            if value is None:
                continue
            if trigger is None:
                return value
            if candidate.direction == "LONG" and value < trigger:
                return value
            if candidate.direction == "SHORT" and value > trigger:
                return value
        return None

    def _is_watch_candidate(self, candidate: TradeSetup) -> bool:
        return bool(
            candidate.entry_valid
            and candidate.direction in {"LONG", "SHORT"}
            and candidate.entry is not None
            and candidate.confidence >= max(WATCH_MIN_CONFIDENCE, settings.setup_confidence_floor - 10)
            and candidate.primary_model_score >= settings.setup_watch_model_score
            and self._primary_model_eligible(candidate)
        )

    def _reset_pending_candidate(self) -> None:
        self._pending_candidate_signature = None
        self._pending_candidate_count = 0
        self._pending_candidate_candle_time = None

    def _candidate_signature(self, candidate: TradeSetup) -> tuple:
        profile = get_instrument(candidate.symbol)
        trigger = self._finite_number(candidate.entry)
        bucket = None if trigger is None else round(trigger / max(profile.tick_size * 4, 1e-9))
        return (candidate.symbol, candidate.direction, candidate.primary_entry_model_key, bucket)

    def _candidate_is_stable(self, candidate: TradeSetup, candle) -> bool:
        """Require distinct closed candles before replacing a live watch.

        The engine polls every few seconds, while the setup evidence is built from
        closed candles. Counting polling cycles caused the old engine to create a
        new LONG/SHORT history row every refresh. Only a new closed candle can now
        advance replacement confirmation.
        """
        signature = self._candidate_signature(candidate)
        if signature != self._pending_candidate_signature:
            self._pending_candidate_signature = signature
            self._pending_candidate_count = 0
            self._pending_candidate_candle_time = None
        if self._pending_candidate_candle_time is None or candle.time > self._pending_candidate_candle_time:
            self._pending_candidate_count += 1
            self._pending_candidate_candle_time = candle.time
        return self._pending_candidate_count >= max(1, settings.direction_switch_confirm_bars)

    def _preview(self, candidate: TradeSetup, status: str | None = None) -> TradeSetup:
        return candidate.model_copy(update={
            "order_state": "PREVIEW_ONLY",
            "actionable": False,
            "status": status or candidate.status,
        })

    @staticmethod
    def _model_confirmation_contract(setup: TradeSetup) -> dict[str, object]:
        contracts = setup.signals.get("model_confirmations") if isinstance(setup.signals, dict) else None
        if not isinstance(contracts, dict):
            return {}
        contract = contracts.get(setup.primary_entry_model_key or "")
        return contract if isinstance(contract, dict) else {}

    @classmethod
    def _confirmation_window_minutes(cls, setup: TradeSetup) -> int:
        contract = cls._model_confirmation_contract(setup)
        try:
            bars = max(1, int(contract.get("window_bars") or 1))
        except (TypeError, ValueError):
            bars = 1
        # Setup evidence is built from completed 5-minute candles. Give each model
        # enough time to print its native confirmation rather than applying the
        # old universal five-minute timeout. The configured minimum remains valid.
        return max(int(settings.watch_confirmation_minutes), bars * 5)

    @classmethod
    def _confirmation_description(cls, setup: TradeSetup) -> tuple[str, list[str]]:
        contract = cls._model_confirmation_contract(setup)
        label = str(contract.get("label") or "model-specific confirmation")
        missing = [str(item) for item in (contract.get("missing") or [])]
        return label, missing

    def _start_watching(
        self, candidate: TradeSetup, candle, *, market_candle=None,
        setup_id: str | None = None, timestamp: datetime | None = None,
    ) -> TradeSetup:
        now = self._utcnow()
        market_candle = market_candle or candle
        watch_expires_at = now + timedelta(minutes=settings.setup_expiry_minutes)
        self._expired_watch = None
        self._reset_pending_candidate()
        trigger = self._finite_number(candidate.entry)
        confirmation_label, missing_confirmation = self._confirmation_description(candidate)
        missing_text = ", ".join(missing_confirmation[:3]) or confirmation_label
        transition_reason = (
            f"TradeIQ is monitoring a {candidate.direction.lower()} {candidate.primary_entry_model or 'entry'} "
            f"candidate near {trigger:,.2f}. No order is armed. Waiting for {missing_text}."
        )
        watching = candidate.model_copy(deep=True, update={
            "setup_id": setup_id or str(uuid4()),
            "timestamp": timestamp or now,
            "valid_until": watch_expires_at,
            "watch_started_at": now,
            "watch_expires_at": watch_expires_at,
            "watch_trigger": trigger,
            "watch_invalidation": self._primary_model_invalidation(candidate),
            "watch_phase": "WAITING_FOR_PRICE",
            "watch_touch_at": None,
            "watch_touch_price": None,
            "watch_touch_candle_time": None,
            "watch_confirmation_expires_at": None,
            "watch_touch_count": 0,
            **self._watch_observation_updates(market_candle),
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
            watching, "PREVIEW_ONLY", "WATCHING", trigger, market_candle.time,
            transition_reason,
            "warning",
        )
        return watching

    def _arm_candidate(
        self, candidate: TradeSetup, candle, *, previous_state: str = "PREVIEW_ONLY",
        setup_id: str | None = None, timestamp: datetime | None = None,
        watch_started_at: datetime | None = None, watch_expires_at: datetime | None = None,
        watch_touch_at: datetime | None = None, watch_touch_price: float | None = None,
        watch_touch_candle_time: datetime | None = None, execution_candle=None,
    ) -> TradeSetup:
        now = self._utcnow()
        execution_candle = execution_candle or candle
        execution_type = str(candidate.execution_type or "LIMIT").upper()
        legacy_default_execution = execution_type == "NONE" and candidate.actionable
        if legacy_default_execution:
            execution_type = "LIMIT"
        if execution_type not in {"MARKET", "LIMIT", "STOP"}:
            return self._preview(candidate, "NO_FRESH_EXECUTION")

        state = "FILLED" if execution_type == "MARKET" else "WAITING_FOR_LIMIT"
        status = "FILLED" if execution_type == "MARKET" else f"WAITING_FOR_{execution_type}"
        entry = float(execution_candle.close) if execution_type == "MARKET" else candidate.entry
        stop = self._finite_number(candidate.stop_loss)
        tp1 = self._finite_number(candidate.take_profit_1)
        tp2 = self._finite_number(candidate.take_profit_2)
        if entry is None or stop is None or tp1 is None or tp2 is None:
            return self._preview(candidate, "INCOMPLETE_EXECUTION_LEVELS")

        risk = abs(float(entry) - stop)
        reward1 = abs(tp1 - float(entry))
        reward2 = abs(tp2 - float(entry))
        if risk <= 0:
            return self._preview(candidate, "INVALID_EXECUTION_RISK")
        tp1_r = round(reward1 / risk, 2)
        tp2_r = round(reward2 / risk, 2)
        effective_tp2_r = max(tp2_r, float(candidate.tp2_r or 0.0))
        if effective_tp2_r < 2.0:
            return self._preview(candidate, "EXECUTION_RR_DEGRADED")
        tp2_r = effective_tp2_r

        execution_detail = candidate.execution_reason
        if legacy_default_execution or not execution_detail or str(execution_detail).startswith("No execution"):
            execution_detail = "The confirmed entry, protective stop, TP1 and TP2 are locked."
        transition_reason = (
            f"The deterministic engine selected {execution_type} execution. "
            f"{execution_detail}"
        )
        action_name = "MARKET_FILLED" if execution_type == "MARKET" else f"{execution_type}_ARMED"
        management_state = "POSITION_ACTIVE" if execution_type == "MARKET" else f"{execution_type}_ARMED"
        updates = {
            "setup_id": setup_id or str(uuid4()),
            "timestamp": timestamp or now,
            "valid_until": now + timedelta(minutes=settings.setup_expiry_minutes),
            "watch_started_at": watch_started_at,
            "watch_expires_at": watch_expires_at,
            "watch_phase": "PLAN_FILLED" if execution_type == "MARKET" else "PLAN_ARMED",
            "watch_touch_at": watch_touch_at,
            "watch_touch_price": watch_touch_price,
            "watch_touch_candle_time": watch_touch_candle_time,
            "watch_confirmation_expires_at": None,
            "order_state": state,
            "status": status,
            "actionable": True,
            "armed_at": now,
            "armed_candle_time": execution_candle.time,
            "entry": round(float(entry), 8),
            "risk_reward": tp2_r,
            "tp1_r": tp1_r,
            "tp2_r": tp2_r,
            **self._execution_observation_updates(execution_candle),
            "last_transition_from": previous_state,
            "last_transition_to": state,
            "last_transition_reason": transition_reason,
            "last_transition_at": now,
            "last_transition_price": float(entry),
            "last_processed_candle_time": candle.time,
            "initial_stop_loss": stop,
            "active_stop_loss": stop,
            "management_state": management_state,
            "partial_exit_percent": settings.partial_exit_percent,
            "runner_active": execution_type == "MARKET",
            "filled_at": now if execution_type == "MARKET" else None,
            "filled_candle_time": execution_candle.time if execution_type == "MARKET" else None,
            "outcome": "OPEN" if execution_type == "MARKET" else None,
            "management_actions": [
                {"at": now.isoformat(), "action": action_name, "detail": transition_reason}
            ],
        }
        armed = candidate.model_copy(deep=True, update=updates)
        storage_service.transition(
            armed, previous_state, state, float(entry), execution_candle.time,
            transition_reason, "positive",
        )
        return armed

    def _evaluate_candidate(self, candidate: TradeSetup, candle, market_candle=None) -> TradeSetup:
        market_candle = market_candle or candle
        can_trade, gate_status = self._market_gate()
        if not can_trade:
            return self._preview(candidate, gate_status)
        if self._same_as_expired_watch(candidate):
            return self._preview(candidate, "WATCH_EXPIRED")
        thesis_block = self._terminal_thesis_block_reason(candidate)
        if thesis_block:
            return self._preview(candidate.model_copy(update={
                "status": "THESIS_LOCKED",
                "actionable": False,
                "execution_type": "NONE",
                "execution_reason": thesis_block,
                "quality_stage": "THESIS_LOCKED",
                "trade_quality_score": 0.0,
                "trade_grade": "—",
                "signals": {**candidate.signals, "thesis_lock_reason": thesis_block},
            }), "THESIS_LOCKED")
        if candidate.actionable:
            return self._arm_candidate(candidate, candle, execution_candle=market_candle)
        if self._is_watch_candidate(candidate):
            return self._start_watching(candidate, candle, market_candle=market_candle)
        return self._preview(candidate)

    # Backward-compatible internal name used by earlier tests and integrations.
    def _maybe_arm(self, candidate: TradeSetup, candle) -> TradeSetup:
        return self._evaluate_candidate(candidate, candle)

    def _advance_watching(self, watching: TradeSetup, candidate: TradeSetup, candle, market_candle=None) -> TradeSetup:
        market_candle = market_candle or candle
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

        # The watch line is not an order, but touching it must produce a visible
        # lifecycle event. TradeIQ now enters a short confirmation window instead
        # of silently doing nothing or instantly discarding the setup.
        trigger = self._finite_number(watching.watch_trigger)
        invalidation = self._finite_number(watching.watch_invalidation)
        invalidated = self._level_touched_after(
            invalidation,
            market_candle,
            observed_candle_time=watching.watch_observed_candle_time,
            observed_low=watching.watch_observed_low,
            observed_high=watching.watch_observed_high,
            observed_close=watching.watch_observed_close,
        )
        if invalidated:
            self._reset_pending_candidate()
            return self._transition(
                watching, "INVALIDATED", market_candle,
                f"The monitored {watching.direction.lower()} thesis was cancelled because price traded through structural invalidation at {invalidation:,.2f} before a limit plan was armed.",
                actionable=False, closed_at=now, outcome="STRUCTURE_FAILED",
            )

        if candidate.actionable and same_direction:
            self._reset_pending_candidate()
            return self._arm_candidate(
                candidate, candle, previous_state="WATCHING",
                setup_id=watching.setup_id, timestamp=watching.timestamp,
                watch_started_at=watching.watch_started_at or watching.timestamp,
                watch_expires_at=watch_expires_at,
                watch_touch_at=watching.watch_touch_at,
                watch_touch_price=watching.watch_touch_price,
                watch_touch_candle_time=watching.watch_touch_candle_time,
                execution_candle=market_candle,
            )

        confirmation_deadline = watching.watch_confirmation_expires_at
        if watching.watch_touch_at is not None and confirmation_deadline and now >= confirmation_deadline:
            confirmation_label, missing_confirmation = self._confirmation_description(candidate)
            missing_text = ", ".join(missing_confirmation[:3]) or confirmation_label
            # A timeout is not structural invalidation. When the thesis remains
            # valid and price is still near the watch location, keep monitoring
            # for one fresh model-native confirmation cycle. This prevents a
            # setup from being labelled "cancelled" immediately before the move.
            distance = abs(float(market_candle.close) - float(trigger or market_candle.close))
            atr_value = self._finite_number(candidate.signals.get("atr")) if isinstance(candidate.signals, dict) else None
            near_watch = distance <= max((atr_value or 0.0) * 0.75, 1.0)
            if self._is_watch_candidate(candidate) and same_direction and near_watch and watching.watch_touch_count < 2:
                extension = self._confirmation_window_minutes(candidate)
                extended_to = min(watch_expires_at, now + timedelta(minutes=extension))
                reason = (
                    f"The first confirmation window ended without {missing_text}, but structural invalidation "
                    "has not failed and price remains near the watch location. Monitoring continues for one fresh confirmation cycle; no order is armed."
                )
                extended = self._refresh_context(watching, candidate).model_copy(update={
                    "watch_phase": "CONFIRMATION_EXTENDED",
                    "status": f"CONFIRMING_{watching.direction}",
                    "watch_confirmation_expires_at": extended_to,
                    "watch_touch_count": watching.watch_touch_count + 1,
                    "last_transition_from": "WATCHING",
                    "last_transition_to": "WATCHING",
                    "last_transition_reason": reason,
                    "last_transition_at": now,
                    "last_transition_price": self._finite_number(market_candle.close),
                    "last_processed_candle_time": candle.time,
                    **self._watch_observation_updates(market_candle),
                })
                storage_service.transition(extended, "WATCHING", "WATCHING", market_candle.close, market_candle.time, reason, "info")
                return extended

            self._remember_expired_watch(watching)
            self._reset_pending_candidate()
            return self._transition(
                watching, "UNCONFIRMED_TOUCH", market_candle,
                f"Price touched the monitoring level, but {missing_text} did not complete before the model-specific confirmation window ended. No order was armed; this is a missed confirmation, not structural invalidation.",
                actionable=False, closed_at=now, outcome="UNCONFIRMED_TOUCH",
            )

        touched_now = self._level_touched_after(
            trigger,
            market_candle,
            observed_candle_time=watching.watch_observed_candle_time,
            observed_low=watching.watch_observed_low,
            observed_high=watching.watch_observed_high,
            observed_close=watching.watch_observed_close,
        )
        if touched_now and watching.watch_touch_at is None:
            window_minutes = self._confirmation_window_minutes(candidate)
            expires = min(watch_expires_at, now + timedelta(minutes=window_minutes))
            confirmation_label, missing_confirmation = self._confirmation_description(candidate)
            waiting_for = ", ".join(missing_confirmation[:3]) or confirmation_label
            reason = (
                f"Price touched the {watching.direction.lower()} watch level at {trigger:,.2f}. "
                f"This is not a fill. The {candidate.primary_entry_model or 'selected'} model now requires "
                f"{waiting_for}. The confirmation window is {window_minutes} minutes."
            )
            touched = self._refresh_context(watching, candidate).model_copy(update={
                "watch_phase": "TRIGGER_TOUCHED",
                "status": f"CONFIRMING_{watching.direction}",
                "watch_touch_at": now,
                "watch_touch_price": self._finite_number(market_candle.close),
                "watch_touch_candle_time": market_candle.time,
                "watch_confirmation_expires_at": expires,
                "watch_touch_count": watching.watch_touch_count + 1,
                "last_transition_from": "WATCHING",
                "last_transition_to": "WATCHING",
                "last_transition_reason": reason,
                "last_transition_at": now,
                "last_transition_price": trigger,
                "last_processed_candle_time": candle.time,
            })
            self._reset_pending_candidate()
            storage_service.transition(touched, "WATCHING", "WATCHING", trigger, market_candle.time, reason, "info")
            return touched

        candidate_watchable = self._is_watch_candidate(candidate)
        model_changed = bool(
            same_direction
            and candidate.primary_entry_model_key
            and candidate.primary_entry_model_key != watching.primary_entry_model_key
            and candidate_watchable
        )

        # Model and direction changes must persist across distinct closed candles.
        # Polling the same candle every two seconds can no longer produce dozens of
        # alternating setup-history rows.
        if model_changed:
            if not self._candidate_is_stable(candidate, candle):
                return watching.model_copy(update={
                    "last_processed_candle_time": candle.time,
                    "status": f"CONFIRMING_{watching.direction}" if watching.watch_touch_at is not None else f"MONITORING_{watching.direction}",
                    **self._watch_observation_updates(market_candle),
                })
            new_trigger = self._finite_number(candidate.entry)
            if new_trigger is not None:
                reason = (
                    f"Primary entry model changed from {watching.primary_entry_model or 'unclassified'} "
                    f"to {candidate.primary_entry_model} at {candidate.primary_model_score:.1f}%. "
                    "The stronger model remained stable across closed candles; no order is armed."
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
                    "watch_invalidation": self._primary_model_invalidation(candidate),
                    "watch_phase": "WAITING_FOR_PRICE",
                    "watch_touch_at": None,
                    "watch_touch_price": None,
                    "watch_touch_candle_time": None,
                    "watch_confirmation_expires_at": None,
                    **self._watch_observation_updates(market_candle),
                    "last_transition_from": "WATCHING",
                    "last_transition_to": "WATCHING",
                    "last_transition_reason": reason,
                    "last_transition_at": now,
                    "last_transition_price": new_trigger,
                    "last_processed_candle_time": candle.time,
                })
                self._reset_pending_candidate()
                storage_service.transition(switched, "WATCHING", "WATCHING", new_trigger, candle.time, reason, "info")
                return switched

        if not same_direction or not candidate_watchable:
            immediate_opposite = bool(not same_direction and candidate.actionable)
            stable = immediate_opposite or self._candidate_is_stable(candidate, candle)
            if not stable:
                return watching.model_copy(update={
                    "last_processed_candle_time": candle.time,
                    "status": f"CONFIRMING_{watching.direction}" if watching.watch_touch_at is not None else f"MONITORING_{watching.direction}",
                    **self._watch_observation_updates(market_candle),
                })
            reason = (
                "A confirmed opposite-direction setup replaced the monitored thesis."
                if immediate_opposite
                else "The monitoring candidate was cancelled after its required confirmations weakened across closed candles."
                if same_direction
                else "The monitoring direction changed and the replacement remained stable across closed candles."
            )
            self._reset_pending_candidate()
            return self._transition(
                watching, "INVALIDATED", candle, reason,
                actionable=False, closed_at=now, outcome="OPPOSITE_SETUP" if not same_direction else "CONFLUENCE_LOST",
            )

        self._reset_pending_candidate()

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
            "status": f"CONFIRMING_{watching.direction}" if watching.watch_touch_at is not None else f"MONITORING_{watching.direction}",
            "order_state": "WATCHING",
            "actionable": False,
            "watch_started_at": watching.watch_started_at or watching.timestamp,
            "watch_expires_at": watch_expires_at,
            "watch_trigger": watching.watch_trigger,
            "watch_invalidation": watching.watch_invalidation,
            "watch_phase": watching.watch_phase,
            "watch_touch_at": watching.watch_touch_at,
            "watch_touch_price": watching.watch_touch_price,
            "watch_touch_candle_time": watching.watch_touch_candle_time,
            "watch_confirmation_expires_at": watching.watch_confirmation_expires_at,
            "watch_touch_count": watching.watch_touch_count,
            **self._watch_observation_updates(market_candle),
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
        if active.order_state == "WATCHING":
            fields.update({
                "location_quality_score": candidate.location_quality_score,
                "confirmation_quality_score": candidate.confirmation_quality_score,
                "execution_quality_score": candidate.execution_quality_score,
                "trade_quality_score": 0.0,
                "trade_grade": "—",
                "quality_stage": candidate.quality_stage,
            })
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
        if new_state in TERMINAL:
            self._remember_terminal_thesis(updated)
        severity = "positive" if new_state in {"FILLED", "TP1_HIT", "TP2_HIT"} else "negative" if new_state == "STOPPED" else "warning"
        storage_service.transition(updated, previous, new_state, candle.close, candle.time, detail, severity)
        return updated

    def _update_excursions(self, active: TradeSetup, candle) -> TradeSetup:
        if active.entry is None or active.order_state not in {"FILLED", "TP1_HIT"}:
            return active

        # On the same live candle that established the current lifecycle state,
        # ignore high/low values already present in the previous observation. They
        # may have occurred before the order filled or before the stop advanced.
        same_observed_candle = (
            active.execution_observed_candle_time is not None
            and candle.time == active.execution_observed_candle_time
        )
        high = float(candle.high)
        low = float(candle.low)
        close = float(candle.close)
        if same_observed_candle:
            observed_high = self._finite_number(active.execution_observed_high)
            observed_low = self._finite_number(active.execution_observed_low)
            effective_high = high if observed_high is None or high > observed_high else close
            effective_low = low if observed_low is None or low < observed_low else close
        else:
            effective_high = high
            effective_low = low

        if active.direction == "LONG":
            favorable = max(0.0, effective_high - active.entry)
            adverse = max(0.0, active.entry - effective_low)
        else:
            favorable = max(0.0, active.entry - effective_low)
            adverse = max(0.0, effective_high - active.entry)
        return active.model_copy(update={
            "max_favorable_excursion_points": round(max(active.max_favorable_excursion_points, favorable), 2),
            "max_adverse_excursion_points": round(max(active.max_adverse_excursion_points, adverse), 2),
        })

    def _tp1_management_updates(self, active: TradeSetup, now: datetime, candle_time: datetime | None = None) -> dict:
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
                "active_stop_effective_candle_time": candle_time,
                "management_actions": actions,
            })
        return updates

    def _advance(self, active: TradeSetup, candidate: TradeSetup, candle) -> TradeSetup:
        # Ignore data older than the live candle observed when the plan was armed.
        if active.armed_candle_time and candle.time < active.armed_candle_time:
            return active.model_copy(update={"last_processed_candle_time": candle.time})

        now = self._utcnow()
        state = active.order_state

        # Backward-compatible restoration guard. Setups persisted before v3.0.3
        # do not contain live observation snapshots. If the first candle we see is
        # the same candle on which the plan/fill/active stop was established, seed
        # the observation instead of interpreting old range extremes as new events.
        if active.execution_observed_candle_time is None:
            reference_time = (
                active.active_stop_effective_candle_time if state == "TP1_HIT"
                else active.filled_candle_time if state == "FILLED"
                else active.armed_candle_time
            )
            if reference_time is not None and candle.time <= reference_time:
                return active.model_copy(update={
                    "last_processed_candle_time": candle.time,
                    **self._execution_observation_updates(candle),
                })

        active = self._update_excursions(active, candle)

        def touched(level: float | None) -> bool:
            return self._level_touched_after(
                self._finite_number(level),
                candle,
                observed_candle_time=active.execution_observed_candle_time,
                observed_low=active.execution_observed_low,
                observed_high=active.execution_observed_high,
                observed_close=active.execution_observed_close,
            )

        def close_reached(level: float | None) -> bool:
            if level is None:
                return False
            if active.direction == "LONG":
                return float(candle.close) >= float(level)
            return float(candle.close) <= float(level)

        observation = self._execution_observation_updates(candle)

        if state == "WAITING_FOR_LIMIT" and now >= active.valid_until:
            return self._transition(
                active, "EXPIRED", candle, "The resting limit was not filled before expiry.",
                actionable=False, closed_at=now, outcome="EXPIRED", **observation,
            )

        if state == "WAITING_FOR_LIMIT":
            # Never keep an unfilled order alive after the expected move has already
            # reached a target. Correct analysis is not permission to chase.
            target_completed_before_fill = bool(
                (active.direction == "LONG" and (float(candle.close) >= float(active.take_profit_1 or float("inf"))))
                or (active.direction == "SHORT" and (float(candle.close) <= float(active.take_profit_1 or float("-inf"))))
            )
            if target_completed_before_fill:
                return self._transition(
                    active, "EXPIRED", candle,
                    "The setup moved to its target path before the selected execution could fill. Analysis was correct, but the entry was missed; no chase is allowed.",
                    actionable=False, closed_at=now, outcome="TARGET_REACHED_BEFORE_FILL", **observation,
                )

            # Cancel stale departures even before the formal timer expires.
            entry_number = self._finite_number(active.entry)
            if entry_number is not None:
                departure = abs(float(candle.close) - entry_number)
                departure_limit = max(float(active.atr or 0.0) * 0.35, get_instrument(active.symbol).tick_size * 12)
                moved_in_trade_direction = bool(
                    (active.direction == "LONG" and float(candle.close) > entry_number)
                    or (active.direction == "SHORT" and float(candle.close) < entry_number)
                )
                if moved_in_trade_direction and departure > departure_limit:
                    return self._transition(
                        active, "EXPIRED", candle,
                        f"The {active.execution_type.lower()} entry became stale after price moved {departure:.2f} points away without filling. No chase; scanning for a secondary continuation model.",
                        actionable=False, closed_at=now, outcome="MISSED_ENTRY_DEPARTURE", **observation,
                    )

            touched_entry = touched(active.entry)
            # A locked resting limit/stop is evaluated before fresh context can cancel it.
            # This prevents the exact fill interval from being mislabeled INVALIDATED.
            if not touched_entry:
                if candidate.direction != active.direction and candidate.confidence >= settings.setup_actionable_score:
                    return self._transition(
                        active, "INVALIDATED", candle,
                        "A strong opposite-direction setup invalidated the unfilled plan.",
                        actionable=False, closed_at=now, outcome="OPPOSITE_SETUP", **observation,
                    )
                if not candidate.actionable and (candidate.confidence < 50 or not candidate.signals.get("gex_alignment") or candidate.cluster_score < .35):
                    return self._transition(
                        active, "INVALIDATED", candle,
                        "The original confluence cluster was lost before entry.",
                        actionable=False, closed_at=now, outcome="CONFLUENCE_LOST", **observation,
                    )
                return active.model_copy(update={"last_processed_candle_time": candle.time, **observation})

            # If entry and stop both became reachable between two observations, the
            # sequence is unknowable from OHLC. Record the conservative stop-first result.
            if touched(active.stop_loss):
                return self._transition(
                    active, "STOPPED", candle,
                    "Entry and stop became reachable within the same observed OHLC interval; conservatively recorded stop-first.",
                    actionable=False, filled_at=now, filled_candle_time=candle.time,
                    closed_at=now, outcome="STOPPED_ON_FILL_CANDLE",
                    management_state="STOPPED", runner_active=False, **observation,
                )

            # A target wick may have occurred before the later pullback filled the
            # limit. Only a close beyond the target proves completion on the first
            # fill observation. Later live updates use post-fill range expansion.
            if close_reached(active.take_profit_2):
                return self._transition(
                    active, "TP2_HIT", candle,
                    "The locked limit filled and the latest traded price completed TP2.",
                    actionable=False, filled_at=now, filled_candle_time=candle.time,
                    closed_at=now, outcome="TP2_HIT", management_state="COMPLETE",
                    runner_active=False, **observation,
                )
            if close_reached(active.take_profit_1):
                return self._transition(
                    active, "TP1_HIT", candle,
                    "The locked limit filled and the latest traded price reached TP1; partial profit was secured and the runner stop advanced according to policy.",
                    filled_at=now, filled_candle_time=candle.time,
                    outcome="TP1_HIT_RUNNING",
                    **self._tp1_management_updates(active, now, candle.time),
                    **observation,
                )
            actions = list(active.management_actions) + [{
                "at": now.isoformat(), "action": "FILLED",
                "detail": "Locked limit filled; risk management is active.",
            }]
            return self._transition(
                active, "FILLED", candle, "The resting limit was filled.",
                filled_at=now, filled_candle_time=candle.time, outcome="OPEN",
                management_state="POSITION_ACTIVE", runner_active=True,
                active_stop_loss=active.active_stop_loss or active.stop_loss,
                management_actions=actions, **observation,
            )

        if state in {"FILLED", "TP1_HIT"}:
            stop_reference = active.active_stop_loss if active.active_stop_loss is not None else active.stop_loss
            stop_touched = touched(stop_reference)
            tp2_touched = touched(active.take_profit_2)
            tp1_touched = touched(active.take_profit_1)

            if stop_touched and tp2_touched:
                return self._transition(
                    active, "STOPPED", candle,
                    "Active stop and TP2 became reachable within one observed OHLC interval; conservatively recorded stop-first.",
                    actionable=False, closed_at=now, outcome="AMBIGUOUS_STOP_FIRST",
                    management_state="STOPPED", runner_active=False, **observation,
                )
            if stop_touched:
                at_breakeven = (
                    state == "TP1_HIT" and active.entry is not None
                    and abs(float(stop_reference) - active.entry) < 1e-9
                )
                detail = "The runner returned to the break-even stop after TP1." if at_breakeven else "The active protective stop was hit."
                outcome = "BREAKEVEN_AFTER_TP1" if at_breakeven else "STOPPED"
                return self._transition(
                    active, "STOPPED", candle, detail, actionable=False,
                    closed_at=now, outcome=outcome,
                    management_state="COMPLETE" if at_breakeven else "STOPPED",
                    runner_active=False, **observation,
                )
            if tp2_touched:
                return self._transition(
                    active, "TP2_HIT", candle, "The final target was reached.",
                    actionable=False, closed_at=now, outcome="TP2_HIT",
                    management_state="COMPLETE", runner_active=False, **observation,
                )
            if state == "FILLED" and tp1_touched:
                return self._transition(
                    active, "TP1_HIT", candle,
                    "The first target was reached; partial profit was secured and the runner is still tracked.",
                    outcome="TP1_HIT_RUNNING",
                    **self._tp1_management_updates(active, now, candle.time),
                    **observation,
                )

        return active.model_copy(update={"last_processed_candle_time": candle.time, **observation})

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
            self._terminal_thesis_locks.clear()
            self._reset_pending_candidate()
            self._restored_setup_id = None
            self._restored_at = None

    def reset_for_symbol(self, symbol: str) -> None:
        with self._lock:
            self._current = None
            self._last_terminal = None
            self._last_processed_candle_time = None
            self._last_error = None
            self._expired_watch = None
            self._terminal_thesis_locks.clear()
            self._reset_pending_candidate()
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
