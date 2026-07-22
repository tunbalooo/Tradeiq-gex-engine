"""Adaptive deterministic execution selection for TradeIQ.

The module decides *how* a confirmed setup should be executed. It never invents
market direction or trade levels; those remain owned by the model ranking and
risk engines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MARKET_KEYS = {
    "LIQUIDITY_SWEEP_MSS", "GAMMA_FLIP_RECLAIM", "VWAP_RECLAIM",
    "TREND_CONTINUATION", "SMT_DIVERGENCE", "INSTITUTIONAL_CONFLUENCE_CLUSTER",
}
LIMIT_KEYS = {
    "SUPPLY_DEMAND_RETEST", "OTE_RETRACEMENT", "FIB_PULLBACK_CONTINUATION",
    "FVG_RETEST", "ORDER_BLOCK_RETEST", "EMA_PULLBACK", "INVERSE_FVG",
}
STOP_KEYS = {"BREAK_RETEST"}


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
) -> ExecutionDecision:
    entry = _number(ideal_entry)
    current = float(current_price)
    atr = max(float(atr or 0.0), float(tick_size) * 8)
    distance = abs(current - entry) if entry is not None else None
    freshness_limit = max(atr * 0.35, float(tick_size) * 12)
    freshness = 0.0 if distance is None else max(0.0, min(100.0, 100.0 * (1.0 - distance / max(freshness_limit, 1e-9))))

    target_reached = False
    if direction == "LONG":
        target_reached = (tp1 is not None and current >= float(tp1)) or (tp2 is not None and current >= float(tp2))
    elif direction == "SHORT":
        target_reached = (tp1 is not None and current <= float(tp1)) or (tp2 is not None and current <= float(tp2))

    common = bool(
        model_confirmed and target_not_blocked and not target_reached
        and (tp2_r or 0.0) >= 2.0 and entry is not None
    )
    if not common:
        reason = "No execution: confirmation, target path, freshness, or minimum 2R safety is incomplete."
        if target_reached:
            reason = "No execution: the expected target path was already reached before an order could be placed."
        return ExecutionDecision("NONE", round(freshness, 1), distance, reason, False)

    # Strong composite clusters can use market execution only while price remains
    # close enough that the original structural stop and reward path are intact.
    market_tolerance = max(atr * 0.22, float(tick_size) * 8)
    if model_key in MARKET_KEYS and distance is not None and distance <= market_tolerance:
        return ExecutionDecision(
            "MARKET", round(freshness, 1), round(distance, 4),
            f"Market execution selected because {model_key.replace('_', ' ').title()} is confirmed, price is only {distance:.2f} points from the ideal entry, and at least 2R remains.",
            True,
        )

    if model_key in STOP_KEYS:
        stop_is_ahead = bool(
            (direction == "LONG" and entry > current)
            or (direction == "SHORT" and entry < current)
        )
        if stop_is_ahead and entry_valid:
            return ExecutionDecision(
                "STOP", round(freshness, 1), round(distance or 0.0, 4),
                "Stop execution selected because the model requires price to prove continuation through the trigger.",
                True,
            )

    if entry_valid and model_key in LIMIT_KEYS | MARKET_KEYS | STOP_KEYS:
        return ExecutionDecision(
            "LIMIT", round(freshness, 1), round(distance or 0.0, 4),
            "Resting limit selected because the ideal retracement remains valid and offers the best structural price.",
            True,
        )

    return ExecutionDecision(
        "NONE", round(freshness, 1), round(distance or 0.0, 4),
        "No execution: the ideal entry is no longer a valid resting or immediate price. The engine will not chase.",
        False,
    )
