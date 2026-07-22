"""Adaptive deterministic execution selection for TradeIQ.

The module decides *how* a confirmed setup should be executed. It never invents
market direction or trade levels; those remain owned by the model ranking and
risk engines.

v3.1.2 separates fast continuation execution from real retracement limits:
- continuation models may enter at market only while the live price is fresh;
- breakout models use stop execution only while the trigger is nearby;
- retracement models may arm a resting limit only at a qualified model level,
  on the correct side of the market, with adequate liquidity room and distance;
- distant watch levels remain internal and never become displayed orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CONTINUATION_KEYS = {
    "LIQUIDITY_SWEEP_MSS", "GAMMA_FLIP_RECLAIM", "VWAP_RECLAIM",
    "TREND_CONTINUATION", "SMT_DIVERGENCE",
}
RETRACEMENT_KEYS = {
    "SUPPLY_DEMAND_RETEST", "OTE_RETRACEMENT", "FIB_PULLBACK_CONTINUATION",
    "FVG_RETEST", "ORDER_BLOCK_RETEST", "EMA_PULLBACK", "INVERSE_FVG",
}
BREAKOUT_KEYS = {"BREAK_RETEST"}
CLUSTER_KEY = "INSTITUTIONAL_CONFLUENCE_CLUSTER"


@dataclass(slots=True)
class ExecutionDecision:
    execution_type: str
    freshness_score: float
    distance_points: float | None
    reason: str
    executable: bool


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _target_reached(direction: str, current: float, tp1: float | None, tp2: float | None) -> bool:
    if direction == "LONG":
        return bool((tp1 is not None and current >= tp1) or (tp2 is not None and current >= tp2))
    if direction == "SHORT":
        return bool((tp1 is not None and current <= tp1) or (tp2 is not None and current <= tp2))
    return False


def _valid_resting_limit(direction: str, current: float, entry: float, tick_size: float) -> bool:
    separation = max(float(tick_size) * 0.5, 1e-9)
    if direction == "LONG":
        return entry <= current - separation
    if direction == "SHORT":
        return entry >= current + separation
    return False


def _valid_stop_trigger(direction: str, current: float, entry: float, tick_size: float) -> bool:
    separation = max(float(tick_size) * 0.5, 1e-9)
    if direction == "LONG":
        return entry >= current + separation
    if direction == "SHORT":
        return entry <= current - separation
    return False


def _remaining_r(direction: str, current: float, stop: float | None, tp2: float | None) -> float | None:
    if stop is None or tp2 is None:
        return None
    risk = abs(current - stop)
    reward = (tp2 - current) if direction == "LONG" else (current - tp2)
    if risk <= 0 or reward <= 0:
        return 0.0
    return reward / risk


def select_execution(
    *,
    model_key: str,
    direction: str,
    current_price: float,
    ideal_entry: float | None,
    atr: float,
    tick_size: float,
    model_confirmed: bool,
    entry_valid: bool,
    target_not_blocked: bool,
    tp1: float | None,
    tp2: float | None,
    tp2_r: float | None,
    composite_score: float = 0.0,
    stop_loss: float | None = None,
    source_model_key: str | None = None,
) -> ExecutionDecision:
    entry = _number(ideal_entry)
    current = float(current_price)
    tick = max(float(tick_size), 1e-9)
    atr = max(float(atr or 0.0), tick * 8)
    tp1_value = _number(tp1)
    tp2_value = _number(tp2)
    stop_value = _number(stop_loss)
    distance = abs(current - entry) if entry is not None else None

    # A limit may be farther than a market entry, but not so far that it is only
    # a speculative watch level. The freshness score is calibrated to that real
    # retracement envelope rather than to the tighter market-entry tolerance.
    limit_distance_cap = max(atr * 0.70, tick * 24)
    freshness_envelope = max(atr * 0.85, tick * 28)
    freshness = 0.0 if distance is None else max(
        0.0,
        min(100.0, 100.0 * (1.0 - distance / max(freshness_envelope, 1e-9))),
    )

    target_reached = _target_reached(direction, current, tp1_value, tp2_value)
    common = bool(
        model_confirmed
        and target_not_blocked
        and not target_reached
        and (tp2_r or 0.0) >= 2.0
        and entry is not None
    )
    if not common:
        reason = "No execution: confirmation, target path, or minimum 2R safety is incomplete."
        if target_reached:
            reason = "No execution: the expected target path was already reached before an order could be placed."
        return ExecutionDecision("NONE", round(freshness, 1), distance, reason, False)

    execution_key = str(source_model_key or model_key or "").upper()
    if model_key == CLUSTER_KEY and not source_model_key:
        execution_key = CLUSTER_KEY

    market_tolerance = max(atr * 0.22, tick * 8)
    at_level_tolerance = max(atr * 0.12, tick * 4)
    stop_distance_cap = max(atr * 0.35, tick * 12)
    current_r = _remaining_r(direction, current, stop_value, tp2_value)
    market_has_room = (current_r is None and (tp2_r or 0.0) >= 2.0) or (current_r is not None and current_r >= 2.0)

    # Fast continuation: once confirmed, take the live price only while it is
    # genuinely close to the intended execution and still offers 2R from now.
    continuation = execution_key in CONTINUATION_KEYS or (
        model_key == CLUSTER_KEY and execution_key == CLUSTER_KEY
    )
    if continuation:
        if distance is not None and distance <= market_tolerance and market_has_room:
            return ExecutionDecision(
                "MARKET",
                round(freshness, 1),
                round(distance, 4),
                f"Market execution selected because the confirmed continuation is only {distance:.2f} points from the institutional entry and at least 2R remains from the live price.",
                True,
            )
        return ExecutionDecision(
            "NONE",
            round(freshness, 1),
            round(distance or 0.0, 4),
            "No execution: the continuation moved beyond the live-entry tolerance. TradeIQ will not convert a missed continuation into a distant limit order.",
            False,
        )

    # Breakout proof: the stop trigger must be in front of price and close enough
    # to represent the current structure rather than an old monitoring level.
    if execution_key in BREAKOUT_KEYS:
        if (
            entry_valid
            and _valid_stop_trigger(direction, current, entry, tick)
            and distance is not None
            and distance <= stop_distance_cap
        ):
            return ExecutionDecision(
                "STOP",
                round(freshness, 1),
                round(distance, 4),
                "Stop execution selected because price must prove continuation through a nearby structural trigger.",
                True,
            )
        return ExecutionDecision(
            "NONE",
            round(freshness, 1),
            round(distance or 0.0, 4),
            "No execution: the breakout trigger is not a fresh nearby stop-entry price.",
            False,
        )

    # Retracement models may execute immediately when confirmation occurs at the
    # intended price. Otherwise they receive a real resting limit only when the
    # selected model level is nearby, on the correct side of market, and has room
    # before opposing liquidity/TP1.
    if execution_key in RETRACEMENT_KEYS:
        if distance is not None and distance <= at_level_tolerance and market_has_room:
            return ExecutionDecision(
                "MARKET",
                round(freshness, 1),
                round(distance, 4),
                "Market execution selected because the retracement confirmed at the intended institutional price and at least 2R remains from the live price.",
                True,
            )

        tp1_room = abs(tp1_value - entry) if tp1_value is not None else None
        minimum_tp1_room = max(atr * 0.45, tick * 12)
        has_liquidity_room = tp1_room is None or tp1_room >= minimum_tp1_room
        real_limit = bool(
            entry_valid
            and _valid_resting_limit(direction, current, entry, tick)
            and distance is not None
            and distance <= limit_distance_cap
            and freshness >= 25.0
            and has_liquidity_room
        )
        if real_limit:
            return ExecutionDecision(
                "LIMIT",
                round(freshness, 1),
                round(distance, 4),
                "Resting limit selected at the confirmed retracement level because it is nearby, structurally valid, fresh, and has sufficient room before opposing liquidity.",
                True,
            )

        if not has_liquidity_room:
            reason = "No execution: the proposed limit is too close to opposing liquidity or TP1 to justify a resting order."
        elif distance is not None and distance > limit_distance_cap:
            reason = "No execution: the retracement level is too far from live price to publish as a real limit order. Monitoring remains internal."
        elif not _valid_resting_limit(direction, current, entry, tick):
            reason = "No execution: the proposed retracement price is not a valid resting limit on the correct side of the market."
        else:
            reason = "No execution: the retracement entry is not fresh enough to arm."
        return ExecutionDecision("NONE", round(freshness, 1), round(distance or 0.0, 4), reason, False)

    return ExecutionDecision(
        "NONE",
        round(freshness, 1),
        round(distance or 0.0, 4),
        "No execution: the selected model does not have a supported deterministic execution route.",
        False,
    )
