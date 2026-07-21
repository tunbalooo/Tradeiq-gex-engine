"""Model-specific entry confirmation rules for TradeIQ.

The ranking engine identifies a location. This module determines whether price
has actually confirmed execution for the selected model. Confirmations are
based on completed candles only; live candles may touch watch levels but cannot
arm a plan by themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.models.schemas import Candle


@dataclass(frozen=True)
class ConfirmationResult:
    confirmed: bool
    label: str
    evidence: list[str]
    missing: list[str]
    window_bars: int


def _ema(values: list[float], length: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (length + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def _body(c: Candle) -> float:
    return abs(c.close - c.open)


def _range(c: Candle) -> float:
    return max(c.high - c.low, 1e-9)


def _directional_close(c: Candle, direction: str) -> bool:
    return c.close > c.open if direction == "LONG" else c.close < c.open


def _strong_close(c: Candle, direction: str) -> bool:
    position = (c.close - c.low) / _range(c)
    return position >= 0.68 if direction == "LONG" else position <= 0.32


def _rejection(c: Candle, direction: str) -> bool:
    body = max(_body(c), _range(c) * 0.08)
    if direction == "LONG":
        lower_wick = min(c.open, c.close) - c.low
        return lower_wick >= body * 1.15 and c.close >= c.low + _range(c) * 0.58
    upper_wick = c.high - max(c.open, c.close)
    return upper_wick >= body * 1.15 and c.close <= c.low + _range(c) * 0.42


def _engulf(previous: Candle, current: Candle, direction: str) -> bool:
    if direction == "LONG":
        return current.close > current.open and current.close >= previous.open and current.open <= previous.close
    return current.close < current.open and current.close <= previous.open and current.open >= previous.close


def _displacement(c: Candle, direction: str, atr: float) -> bool:
    return (
        _directional_close(c, direction)
        and _body(c) >= max(atr * 0.38, _range(c) * 0.58)
        and _strong_close(c, direction)
    )


def _touches(c: Candle, low: float | None, high: float | None) -> bool:
    if low is None and high is None:
        return False
    lo = float(low if low is not None else high)
    hi = float(high if high is not None else low)
    if lo > hi:
        lo, hi = hi, lo
    return c.low <= hi and c.high >= lo


def _reclaim(previous: Candle, current: Candle, level: float | None, direction: str) -> bool:
    if level is None:
        return False
    level = float(level)
    if direction == "LONG":
        return previous.close <= level and current.close > level and current.low <= level
    return previous.close >= level and current.close < level and current.high >= level


def _hold_after_touch(candles: list[Candle], level: float | None, direction: str) -> bool:
    if level is None or len(candles) < 3:
        return False
    level = float(level)
    recent = candles[-3:]
    touched = any(c.low <= level <= c.high for c in recent)
    if not touched:
        return False
    if direction == "LONG":
        return recent[-1].close > level and recent[-2].close > level
    return recent[-1].close < level and recent[-2].close < level


def _micro_shift(previous: Candle, current: Candle, direction: str) -> bool:
    return current.close > previous.high if direction == "LONG" else current.close < previous.low


def _result(label: str, checks: list[tuple[str, bool]], *, window_bars: int, require: int | None = None) -> ConfirmationResult:
    evidence = [name for name, ok in checks if ok]
    missing = [name for name, ok in checks if not ok]
    needed = len(checks) if require is None else require
    return ConfirmationResult(len(evidence) >= needed, label, evidence, missing, window_bars)


def evaluate_model_confirmations(
    candles: list[Candle], *, direction: str, atr: float, vwap: float | None,
    gamma_flip: float | None, zone_low: float | None, zone_high: float | None,
    ote_low: float | None, ote_high: float | None, fvg_low: float | None,
    fvg_high: float | None, previous_liquidity_low: float | None,
    previous_liquidity_high: float | None, signals: dict[str, Any],
) -> dict[str, ConfirmationResult]:
    """Return an explicit confirmation contract for every entry model."""
    if len(candles) < 5:
        empty = ConfirmationResult(False, "Insufficient completed candles", [], ["completed candle history"], 3)
        return {key: empty for key in (
            "LIQUIDITY_SWEEP_MSS", "SUPPLY_DEMAND_RETEST", "OTE_RETRACEMENT",
            "FIB_PULLBACK_CONTINUATION", "GAMMA_FLIP_RECLAIM", "FVG_RETEST",
            "ORDER_BLOCK_RETEST", "EMA_PULLBACK", "VWAP_RECLAIM", "BREAK_RETEST",
            "TREND_CONTINUATION", "INVERSE_FVG", "SMT_DIVERGENCE",
        )}

    previous, current = candles[-2], candles[-1]
    closes = [c.close for c in candles[-80:]]
    ema9, ema21, ema55 = (_ema(closes, n) for n in (9, 21, 55))
    e9, e21, e55 = ema9[-1], ema21[-1], ema55[-1]
    band_low, band_high = min(e9, e21), max(e9, e21)

    reject = _rejection(current, direction)
    engulf = _engulf(previous, current, direction)
    displacement = _displacement(current, direction, atr)
    micro_shift = _micro_shift(previous, current, direction)
    directional_close = _directional_close(current, direction) and _strong_close(current, direction)
    zone_touch = any(_touches(c, zone_low, zone_high) for c in candles[-3:])
    ote_touch = any(_touches(c, ote_low, ote_high) for c in candles[-3:])
    fvg_touch = any(_touches(c, fvg_low, fvg_high) for c in candles[-3:])
    ema_touch = any(_touches(c, band_low, band_high) for c in candles[-3:])
    ema_reclaim = current.close > band_high if direction == "LONG" else current.close < band_low
    ema_stack = e9 > e21 > e55 if direction == "LONG" else e9 < e21 < e55
    gamma_reclaim = _reclaim(previous, current, gamma_flip, direction) or _hold_after_touch(candles, gamma_flip, direction)
    vwap_reclaim = _reclaim(previous, current, vwap, direction) or _hold_after_touch(candles, vwap, direction)
    break_level = previous_liquidity_high if direction == "LONG" else previous_liquidity_low
    break_confirm = False
    retest_confirm = False
    if break_level is not None:
        level = float(break_level)
        break_confirm = previous.close > level if direction == "LONG" else previous.close < level
        retest_confirm = current.low <= level <= current.high and (current.close > level if direction == "LONG" else current.close < level)

    inverse_fvg = bool(signals.get("inverse_fvg"))
    ifvg_mid = signals.get("inverse_fvg_mid")
    ifvg_hold = _hold_after_touch(candles, ifvg_mid, direction) or _reclaim(previous, current, ifvg_mid, direction)

    sweep = bool(signals.get("liquidity_sweep"))
    ordered = bool(signals.get("ordered_sequence"))
    fib_confirmed = bool(signals.get("fib_pullback_confirmed"))
    fib_fresh = bool(signals.get("fib_pullback_entry_fresh"))
    smt = bool(signals.get("smt_divergence"))

    # Each contract mixes location evidence with a model-native trigger. A single
    # generic rejection candle is intentionally not used for every strategy.
    return {
        "LIQUIDITY_SWEEP_MSS": _result(
            "Sweep reclaimed and market structure shifted",
            [("directional liquidity sweep", sweep), ("micro structure shift", micro_shift or ordered), ("directional displacement", displacement)],
            window_bars=3, require=3,
        ),
        "SUPPLY_DEMAND_RETEST": _result(
            "Zone held with rejection or displacement away",
            [("supply/demand zone touched", zone_touch), ("zone rejection", reject or engulf), ("close away from zone", directional_close or displacement)],
            window_bars=4, require=2,
        ),
        "OTE_RETRACEMENT": _result(
            "OTE held and continuation resumed",
            [("OTE zone touched", ote_touch), ("rejection or engulfing response", reject or engulf), ("micro structure shift or displacement", micro_shift or displacement)],
            window_bars=4, require=2,
        ),
        "FIB_PULLBACK_CONTINUATION": _result(
            "50%–61.8% pullback confirmed by a closed continuation candle",
            [("fib pullback touched", bool(signals.get("fib_pullback_touched"))), ("closed fib rejection/reclaim", fib_confirmed), ("confirmation entry remains fresh", fib_fresh)],
            window_bars=5, require=3,
        ),
        "GAMMA_FLIP_RECLAIM": _result(
            "Gamma Flip reclaimed and held",
            [("Gamma Flip reclaim/hold", gamma_reclaim), ("directional close", directional_close), ("trend alignment", bool(signals.get("trend_alignment")))],
            window_bars=3, require=2,
        ),
        "FVG_RETEST": _result(
            "FVG retest rejected with continuation displacement",
            [("FVG touched", fvg_touch), ("rejection from imbalance", reject or engulf), ("displacement or micro shift", displacement or micro_shift)],
            window_bars=4, require=2,
        ),
        "ORDER_BLOCK_RETEST": _result(
            "Order block defended and displaced",
            [("order-block zone touched", zone_touch), ("rejection/engulfing candle", reject or engulf), ("displacement away", displacement)],
            window_bars=4, require=2,
        ),
        "EMA_PULLBACK": _result(
            "EMA 9/21 pullback reclaimed in trend direction",
            [("EMA 9/21 band touched", ema_touch), ("EMA stack aligned", ema_stack), ("close reclaimed EMA band", ema_reclaim), ("continuation candle", engulf or displacement or directional_close)],
            window_bars=3, require=3,
        ),
        "VWAP_RECLAIM": _result(
            "VWAP reclaimed and accepted",
            [("VWAP reclaim/hold", vwap_reclaim), ("directional close", directional_close), ("trend alignment", bool(signals.get("trend_alignment")))],
            window_bars=3, require=2,
        ),
        "BREAK_RETEST": _result(
            "Broken liquidity level retested and held",
            [("liquidity level broken", break_confirm), ("broken level retested", retest_confirm), ("continuation close", directional_close or displacement)],
            window_bars=4, require=3,
        ),
        "TREND_CONTINUATION": _result(
            "Shallow trend pullback ended with renewed momentum",
            [("EMA trend stack aligned", ema_stack), ("shallow EMA pullback", ema_touch), ("renewed directional momentum", displacement or engulf or micro_shift)],
            window_bars=3, require=2,
        ),
        "INVERSE_FVG": _result(
            "Opposing FVG flipped and held as support/resistance",
            [("inverse FVG identified", inverse_fvg), ("inverse FVG reclaim/hold", ifvg_hold), ("directional displacement", displacement or micro_shift)],
            window_bars=4, require=3,
        ),
        "SMT_DIVERGENCE": _result(
            "SMT divergence confirmed by sweep and structure shift",
            [("SMT divergence", smt), ("liquidity sweep", sweep), ("structure shift/displacement", micro_shift or displacement or ordered)],
            window_bars=4, require=3,
        ),
    }
