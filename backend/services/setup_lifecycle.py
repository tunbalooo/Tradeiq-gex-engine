import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.core.config import settings
from backend.models.schemas import Candle, TradeSetup


TERMINAL_STATES = {"STOPPED", "TP2_HIT", "EXPIRED", "INVALIDATED"}
ACTIVE_STATES = {"WAITING_FOR_LIMIT", "FILLED", "TP1_HIT"}


class SetupLifecycleService:
    """Freeze actionable trade plans and track their candle-based lifecycle.

    This service does not send broker orders. It only changes the dashboard's
    state from preview -> armed -> filled -> completed/invalidated.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._active: TradeSetup | None = None
        self._last_terminal: TradeSetup | None = None

    def reset(self) -> None:
        with self._lock:
            self._active = None
            self._last_terminal = None

    def health(self) -> dict:
        with self._lock:
            return {
                "active_setup_id": self._active.setup_id if self._active else None,
                "order_state": self._active.order_state if self._active else "NONE",
                "last_outcome": self._last_terminal.outcome if self._last_terminal else None,
            }

    def process(self, candidate: TradeSetup, candle: Candle) -> TradeSetup:
        with self._lock:
            if self._active is not None:
                updated = self._advance(self._active, candidate, candle)
                if updated.order_state in TERMINAL_STATES:
                    self._last_terminal = updated
                    self._active = None
                else:
                    self._active = updated
                return updated

            if candidate.actionable:
                now = datetime.now(timezone.utc)
                armed = candidate.model_copy(
                    deep=True,
                    update={
                        "setup_id": str(uuid4()),
                        "timestamp": now,
                        "valid_until": now + timedelta(minutes=settings.setup_expiry_minutes),
                        "order_state": "WAITING_FOR_LIMIT",
                        "status": "WAITING_FOR_LIMIT",
                        "actionable": True,
                    },
                )
                self._active = armed
                return armed

            return candidate

    def _refresh_context(self, active: TradeSetup, candidate: TradeSetup) -> TradeSetup:
        """Refresh live analysis while preserving the frozen trade prices and ID."""
        return active.model_copy(update={
            "confidence": candidate.confidence,
            "confidence_components": candidate.confidence_components,
            "confidence_maximums": candidate.confidence_maximums,
            "signals": candidate.signals,
            "rationale": candidate.rationale,
            "gex": candidate.gex,
            "zones": candidate.zones,
            "fib_levels": candidate.fib_levels,
            "atr": candidate.atr,
            "vwap": candidate.vwap,
            "standard_deviation_high": candidate.standard_deviation_high,
            "standard_deviation_low": candidate.standard_deviation_low,
            "cluster_score": candidate.cluster_score,
            "cluster_low": candidate.cluster_low,
            "cluster_high": candidate.cluster_high,
            "cluster_gex_level": candidate.cluster_gex_level,
            "cluster_gex_type": candidate.cluster_gex_type,
            "selected_zone_low": candidate.selected_zone_low,
            "selected_zone_high": candidate.selected_zone_high,
            "selected_zone_timeframe": candidate.selected_zone_timeframe,
        })

    def _advance(self, active: TradeSetup, candidate: TradeSetup, candle: Candle) -> TradeSetup:
        now = datetime.now(timezone.utc)
        active = self._refresh_context(active, candidate)
        state = active.order_state

        if now >= active.valid_until and state == "WAITING_FOR_LIMIT":
            return active.model_copy(update={
                "order_state": "EXPIRED", "status": "EXPIRED", "actionable": False,
                "closed_at": now, "outcome": "EXPIRED",
            })

        # A strong opposite candidate invalidates an unfilled frozen plan.
        if (
            state == "WAITING_FOR_LIMIT"
            and candidate.direction != active.direction
            and candidate.confidence >= 75
        ):
            return active.model_copy(update={
                "order_state": "INVALIDATED", "status": "INVALIDATED", "actionable": False,
                "closed_at": now, "outcome": "OPPOSITE_SETUP",
            })

        if (
            state == "WAITING_FOR_LIMIT"
            and (candidate.confidence < 50 or not candidate.signals.get("gex_alignment") or candidate.cluster_score < 0.35)
        ):
            return active.model_copy(update={
                "order_state": "INVALIDATED", "status": "INVALIDATED", "actionable": False,
                "closed_at": now, "outcome": "CONFLUENCE_LOST",
            })

        if state == "WAITING_FOR_LIMIT":
            touched_entry = (
                candle.low <= active.entry if active.direction == "LONG" else candle.high >= active.entry
            )
            if not touched_entry:
                return active

            # Conservative OHLC handling: if the fill candle also touches the stop,
            # record the stop first because intrabar path is unknown.
            stop_touched = (
                candle.low <= active.stop_loss if active.direction == "LONG" else candle.high >= active.stop_loss
            )
            if stop_touched:
                return active.model_copy(update={
                    "order_state": "STOPPED", "status": "STOPPED", "actionable": False,
                    "filled_at": now, "closed_at": now, "outcome": "STOPPED_ON_FILL_CANDLE",
                })

            tp2_touched = (
                candle.high >= active.take_profit_2 if active.direction == "LONG" else candle.low <= active.take_profit_2
            )
            tp1_touched = (
                candle.high >= active.take_profit_1 if active.direction == "LONG" else candle.low <= active.take_profit_1
            )
            if tp2_touched:
                return active.model_copy(update={
                    "order_state": "TP2_HIT", "status": "TP2_HIT", "actionable": False,
                    "filled_at": now, "closed_at": now, "outcome": "TP2_HIT",
                })
            if tp1_touched:
                return active.model_copy(update={
                    "order_state": "TP1_HIT", "status": "TP1_HIT", "filled_at": now,
                    "outcome": "TP1_HIT_RUNNING",
                })
            return active.model_copy(update={
                "order_state": "FILLED", "status": "FILLED", "filled_at": now,
                "outcome": "OPEN",
            })

        if state in {"FILLED", "TP1_HIT"}:
            stop_touched = (
                candle.low <= active.stop_loss if active.direction == "LONG" else candle.high >= active.stop_loss
            )
            tp2_touched = (
                candle.high >= active.take_profit_2 if active.direction == "LONG" else candle.low <= active.take_profit_2
            )
            tp1_touched = (
                candle.high >= active.take_profit_1 if active.direction == "LONG" else candle.low <= active.take_profit_1
            )
            if stop_touched and tp2_touched:
                return active.model_copy(update={
                    "order_state": "STOPPED", "status": "STOPPED", "actionable": False,
                    "closed_at": now, "outcome": "AMBIGUOUS_STOP_FIRST",
                })
            if stop_touched:
                return active.model_copy(update={
                    "order_state": "STOPPED", "status": "STOPPED", "actionable": False,
                    "closed_at": now, "outcome": "STOPPED",
                })
            if tp2_touched:
                return active.model_copy(update={
                    "order_state": "TP2_HIT", "status": "TP2_HIT", "actionable": False,
                    "closed_at": now, "outcome": "TP2_HIT",
                })
            if state == "FILLED" and tp1_touched:
                return active.model_copy(update={
                    "order_state": "TP1_HIT", "status": "TP1_HIT", "outcome": "TP1_HIT_RUNNING",
                })
        return active


setup_lifecycle_service = SetupLifecycleService()
