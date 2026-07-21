"""Deterministic multi-model ranking for TradeIQ v3.0.

Models rank evidence; they do not place orders. The existing risk engine remains
responsible for producing an executable entry, stop and targets after the
selected model and mandatory safety gates qualify.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from backend.models.schemas import EntryModelScore


def _q(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _proximity(price: float | None, level: float | None, atr: float) -> float:
    if price is None or level is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - abs(float(price) - float(level)) / max(atr * 2.0, 0.25)))


@dataclass(slots=True)
class ModelContext:
    direction: str
    current_price: float
    atr: float
    proposed_entry: float | None
    vwap: float | None
    gamma_flip: float | None
    selected_zone_low: float | None
    selected_zone_high: float | None
    ote_low: float | None
    ote_high: float | None
    fvg_low: float | None
    fvg_high: float | None
    signals: dict[str, Any]
    structure: dict[str, Any]
    fib_pullback_low: float | None = None
    fib_pullback_high: float | None = None
    fib_pullback_confirmation_entry: float | None = None
    fib_pullback_invalidation: float | None = None
    volume_expansion: float = 0.0
    session_quality: float = 0.0

    @property
    def zone_mid(self) -> float | None:
        if self.selected_zone_low is None or self.selected_zone_high is None:
            return None
        return (self.selected_zone_low + self.selected_zone_high) / 2.0

    @property
    def ote_mid(self) -> float | None:
        if self.ote_low is None or self.ote_high is None:
            return None
        return (self.ote_low + self.ote_high) / 2.0

    @property
    def fvg_mid(self) -> float | None:
        if self.fvg_low is None or self.fvg_high is None:
            return None
        return (self.fvg_low + self.fvg_high) / 2.0

    @property
    def fib_pullback_mid(self) -> float | None:
        if self.fib_pullback_low is None or self.fib_pullback_high is None:
            return None
        return (self.fib_pullback_low + self.fib_pullback_high) / 2.0


def _score(name: str, key: str, direction: str, factors: Iterable[tuple[float, float]], *,
           trigger: float | None, invalidation: float | None, reason: list[str], missing: list[str],
           minimum: float = 45.0, priority: int = 50) -> EntryModelScore:
    weighted = list(factors)
    denominator = sum(weight for weight, _ in weighted) or 1.0
    raw = sum(weight * _q(value) for weight, value in weighted) / denominator * 100.0
    score = round(max(0.0, min(100.0, raw)), 1)
    eligible = trigger is not None and score >= minimum and not missing
    return EntryModelScore(
        key=key,
        name=name,
        direction=direction,
        score=score,
        eligible=eligible,
        priority=priority,
        trigger_price=round(trigger, 2) if trigger is not None else None,
        invalidation_price=round(invalidation, 2) if invalidation is not None else None,
        reason=reason,
        missing=missing,
    )


def rank_entry_models(context: ModelContext) -> list[EntryModelScore]:
    s = context.signals
    st = context.structure
    trend = _q(s.get("trend_alignment"))
    gex = _q(s.get("gex_alignment"))
    sweep = _q(s.get("liquidity_sweep"))
    displacement = _q(s.get("displacement"))
    fvg = _q(s.get("directional_fvg"))
    sequence = _q(s.get("ordered_sequence"))
    zone = _q(s.get("supply_demand"))
    ote = _q(s.get("ote_overlap"))
    cluster = _q(s.get("gex_ote_zone_cluster"))
    vwap = _q(s.get("vwap_alignment"))
    rr = _q(s.get("target_not_blocked"))
    volume = _q(context.volume_expansion)
    session = _q(context.session_quality)
    fib_impulse = _q(s.get("fib_pullback_impulse_quality"))
    fib_touched = _q(s.get("fib_pullback_touched"))
    fib_rejection = _q(s.get("fib_pullback_rejection"))
    fib_confirmed = _q(s.get("fib_pullback_confirmed"))
    fib_fresh = _q(s.get("fib_pullback_entry_fresh"))

    zone_kind = "Demand" if context.direction == "LONG" else "Supply"
    invalidation = context.selected_zone_low if context.direction == "LONG" else context.selected_zone_high
    results = [
        _score(
            "Liquidity Sweep + Structure Shift", "LIQUIDITY_SWEEP_MSS", context.direction,
            [(28, sweep), (24, displacement), (20, sequence), (12, trend), (8, gex), (8, rr)],
            trigger=context.proposed_entry, invalidation=st.get("sweep_price"),
            reason=["Directional liquidity sweep", "Displacement/structure confirmation", "Risk remains acceptable"],
            missing=[] if sweep and displacement else ["liquidity sweep and displacement"], minimum=55, priority=1,
        ),
        _score(
            f"{zone_kind} Zone Retest", "SUPPLY_DEMAND_RETEST", context.direction,
            [(30, zone), (20, cluster), (16, trend), (14, gex), (10, displacement), (10, rr)],
            trigger=context.zone_mid or context.proposed_entry, invalidation=invalidation,
            reason=[f"Fresh {zone_kind.lower()} evidence", "GEX/OTE cluster support", "Trend alignment"],
            missing=[] if context.zone_mid is not None else [f"active {zone_kind.lower()} zone"], minimum=50, priority=2,
        ),
        _score(
            "OTE Retracement", "OTE_RETRACEMENT", context.direction,
            [(30, ote), (22, cluster), (16, trend), (12, gex), (10, displacement), (10, rr)],
            trigger=context.ote_mid or context.proposed_entry, invalidation=invalidation,
            reason=["Entry overlaps the institutional retracement window", "Confluence cluster supports the level"],
            missing=[] if context.ote_mid is not None else ["valid OTE range"], minimum=50, priority=3,
        ),
        _score(
            "Fib Pullback Continuation", "FIB_PULLBACK_CONTINUATION", context.direction,
            [(22, fib_impulse), (18, trend), (16, fib_touched), (18, fib_rejection),
             (10, displacement), (8, max(zone, cluster)), (5, gex), (3, rr)],
            trigger=(context.fib_pullback_confirmation_entry if fib_confirmed else context.fib_pullback_mid),
            invalidation=context.fib_pullback_invalidation or invalidation,
            reason=[
                "A directional impulse defines a 50%–61.8% continuation zone",
                "Execution requires a closed rejection/reclaim candle",
                "The executable limit uses the confirmation candle body midpoint",
            ],
            missing=[] if context.fib_pullback_mid is not None and fib_impulse >= .5 and trend
                else ["clear directional impulse, aligned trend and valid 50%–61.8% zone"],
            minimum=50, priority=4,
        ),
        _score(
            "Gamma Flip Reclaim", "GAMMA_FLIP_RECLAIM", context.direction,
            [(32, gex), (22, _proximity(context.current_price, context.gamma_flip, context.atr)), (16, trend), (12, displacement), (10, vwap), (8, rr)],
            trigger=context.gamma_flip, invalidation=(context.gamma_flip - context.atr * .35 if context.direction == "LONG" and context.gamma_flip is not None else context.gamma_flip + context.atr * .35 if context.gamma_flip is not None else None),
            reason=["Price is interacting with the dealer pivot", "Directional structure supports the reclaim"],
            missing=[] if context.gamma_flip is not None else ["gamma flip"], minimum=55, priority=5,
        ),
        _score(
            "Fair Value Gap Retest", "FVG_RETEST", context.direction,
            [(30, fvg), (22, displacement), (18, sequence), (12, trend), (10, gex), (8, rr)],
            trigger=context.fvg_mid, invalidation=context.fvg_low if context.direction == "LONG" else context.fvg_high,
            reason=["Directional imbalance is available for a retest", "Displacement created the gap"],
            missing=[] if context.fvg_mid is not None else ["directional fair value gap"], minimum=52, priority=6,
        ),
        _score(
            "Order Block Retest", "ORDER_BLOCK_RETEST", context.direction,
            [(28, zone), (24, displacement), (16, sequence), (12, trend), (10, cluster), (10, rr)],
            trigger=context.zone_mid or context.proposed_entry, invalidation=invalidation,
            reason=["Displacement originated from the selected institutional zone", "Structure remains aligned"],
            missing=[] if context.zone_mid is not None and displacement else ["displacement-backed order block"], minimum=56, priority=7,
        ),
        _score(
            "EMA Pullback", "EMA_PULLBACK", context.direction,
            [(34, trend), (18, displacement), (14, vwap), (12, gex), (12, volume), (10, rr)],
            trigger=context.proposed_entry, invalidation=invalidation,
            reason=["9/21/55 trend alignment", "Continuation momentum remains constructive"],
            missing=[] if trend else ["9/21/55 alignment"], minimum=48, priority=8,
        ),
        _score(
            "VWAP Reclaim", "VWAP_RECLAIM", context.direction,
            [(34, vwap), (20, trend), (16, displacement), (12, gex), (10, volume), (8, rr)],
            trigger=context.vwap, invalidation=(context.vwap - context.atr * .35 if context.direction == "LONG" and context.vwap is not None else context.vwap + context.atr * .35 if context.vwap is not None else None),
            reason=["Price is on the directional side of VWAP", "Trend and momentum support a reclaim"],
            missing=[] if context.vwap is not None and vwap else ["confirmed directional VWAP reclaim"], minimum=52, priority=9,
        ),
        _score(
            "Break & Retest", "BREAK_RETEST", context.direction,
            [(28, displacement), (24, trend), (18, sequence), (12, volume), (10, gex), (8, rr)],
            trigger=context.proposed_entry, invalidation=st.get("previous_liquidity_low") if context.direction == "LONG" else st.get("previous_liquidity_high"),
            reason=["Directional break has displacement", "Retest location retains reward room"],
            missing=[] if displacement and trend else ["directional break with trend alignment"], minimum=54, priority=10,
        ),
        _score(
            "Trend Continuation", "TREND_CONTINUATION", context.direction,
            [(32, trend), (20, displacement), (14, volume), (12, vwap), (10, gex), (7, session), (5, rr)],
            trigger=context.proposed_entry, invalidation=invalidation,
            reason=["Trend structure is aligned", "Momentum and session quality support continuation"],
            missing=[] if trend else ["aligned trend"], minimum=48, priority=11,
        ),
        _score(
            "Inverse FVG", "INVERSE_FVG", context.direction,
            [(30, _q(s.get("inverse_fvg"))), (22, displacement), (18, trend), (12, sweep), (10, gex), (8, rr)],
            trigger=s.get("inverse_fvg_mid"), invalidation=s.get("inverse_fvg_invalidation"),
            reason=["Opposing imbalance converted into support/resistance"],
            missing=[] if s.get("inverse_fvg") and s.get("inverse_fvg_mid") is not None else ["confirmed inverse FVG"], minimum=55, priority=12,
        ),
        _score(
            "SMT Divergence", "SMT_DIVERGENCE", context.direction,
            [(35, _q(s.get("smt_divergence"))), (20, sweep), (15, displacement), (12, trend), (10, gex), (8, rr)],
            trigger=context.proposed_entry, invalidation=invalidation,
            reason=["Cross-market divergence confirms institutional asymmetry"],
            missing=[] if s.get("smt_divergence") else ["synchronized comparison-market data"], minimum=58, priority=13,
        ),
    ]
    return sorted(results, key=lambda item: (not item.eligible, -item.score, item.priority, item.name))
