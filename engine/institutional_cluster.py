"""Independent-evidence institutional confluence cluster scoring.

TradeIQ may trade a strong single model or a spatially aligned cluster. Cluster
strength is based on independent evidence categories, not the raw number of
labels. Two-factor clusters are allowed only when both categories are unusually
strong; three-factor clusters are standard; four-or-more-factor clusters receive
high-priority status, subject to the same execution and risk gates as any setup.
"""
from __future__ import annotations

from typing import Any

from backend.core.config import settings
from backend.models.schemas import EntryModelScore


CATEGORY_WEIGHTS = {
    "gex": 18.0,
    "zone": 18.0,
    "retracement": 14.0,
    "imbalance": 14.0,
    "liquidity_structure": 22.0,
    "trend_value": 14.0,
}


def _q(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _cluster_tier(category_count: int) -> tuple[str, float, float, int, float]:
    """Return tier, minimum score, confidence, confirmation strength and freshness.

    The final execution decision still requires a valid structural stop, clear
    target path, minimum 2R and healthy data. These values only define the extra
    quality required for each cluster breadth tier.
    """
    if category_count >= 4:
        return (
            "HIGH_PRIORITY_4_PLUS",
            float(settings.cluster_four_factor_min_score),
            float(settings.setup_confidence_floor),
            1,
            float(settings.cluster_four_factor_min_freshness),
        )
    if category_count == 3:
        return (
            "STANDARD_3_FACTOR",
            float(settings.cluster_three_factor_min_score),
            max(float(settings.setup_confidence_floor), float(settings.cluster_three_factor_min_confidence)),
            1,
            float(settings.cluster_three_factor_min_freshness),
        )
    if category_count == 2:
        return (
            "EXCEPTIONAL_2_FACTOR",
            float(settings.cluster_two_factor_min_score),
            max(float(settings.setup_confidence_floor), float(settings.cluster_two_factor_min_confidence)),
            2,
            float(settings.cluster_two_factor_min_freshness),
        )
    return ("NONE", 101.0, 101.0, 99, 101.0)


def build_cluster_score(
    signals: dict[str, Any],
    ranking: list[EntryModelScore],
    cluster_score: float,
) -> dict[str, Any]:
    # Related labels are grouped so OTE/Fib and Supply/Order Block cannot inflate
    # confidence by double-counting the same location concept.
    categories = {
        "gex": max(_q(signals.get("gex_alignment")), _q(signals.get("gex_inside_cluster"))),
        "zone": max(_q(signals.get("supply_demand")), _q(signals.get("gex_ote_zone_cluster"))),
        "retracement": max(_q(signals.get("ote_overlap")), _q(signals.get("fib_pullback_touched"))),
        "imbalance": max(_q(signals.get("directional_fvg")), _q(signals.get("inverse_fvg"))),
        "liquidity_structure": max(
            _q(signals.get("liquidity_sweep")),
            _q(signals.get("ordered_sequence")),
            _q(signals.get("displacement")),
        ),
        "trend_value": max(_q(signals.get("trend_alignment")), _q(signals.get("vwap_alignment"))),
    }

    weighted_total = sum(CATEGORY_WEIGHTS[key] * categories[key] for key in CATEGORY_WEIGHTS)
    active = [key for key, value in categories.items() if value >= 0.6]
    active_weight = sum(CATEGORY_WEIGHTS[key] for key in active)
    active_weighted = sum(CATEGORY_WEIGHTS[key] * categories[key] for key in active)
    active_quality = (active_weighted / active_weight * 100.0) if active_weight else 0.0

    # Breadth matters, but it cannot compensate for weak factors. The weighted
    # active-quality term allows an exceptional two-factor location to qualify,
    # while the breadth bonus makes three and four-plus independent categories
    # progressively more valuable.
    breadth_bonus = {0: 0.0, 1: 0.0, 2: 10.0, 3: 16.0, 4: 22.0, 5: 26.0, 6: 30.0}.get(
        len(active), 30.0
    )
    spatial_boost = max(0.0, min(1.0, float(cluster_score or 0.0))) * 8.0
    score = min(
        100.0,
        active_quality * 0.55 + weighted_total * 0.15 + breadth_bonus + spatial_boost,
    )

    tier, minimum_score, minimum_confidence, required_confirmation_strength, minimum_freshness = _cluster_tier(len(active))
    eligible = bool(len(active) >= 2 and score >= minimum_score)

    # Tier bonuses are used only to compare a composite cluster with the strongest
    # valid single model. The raw score remains visible and auditable.
    selection_bonus = {
        "EXCEPTIONAL_2_FACTOR": 4.0,
        "STANDARD_3_FACTOR": 7.0,
        "HIGH_PRIORITY_4_PLUS": 10.0,
    }.get(tier, 0.0)
    selection_score = min(100.0, score + selection_bonus)

    contributors = [item.name for item in ranking if item.eligible and item.score >= 60][:6]
    return {
        "score": round(score, 1),
        "selection_score": round(selection_score, 1),
        "selection_bonus": selection_bonus,
        "eligible": eligible,
        "tier": tier,
        "category_count": len(active),
        "minimum_score": minimum_score,
        "minimum_confidence": minimum_confidence,
        "required_confirmation_strength": required_confirmation_strength,
        "minimum_freshness": minimum_freshness,
        "categories": {key: round(categories[key] * CATEGORY_WEIGHTS[key], 1) for key in categories},
        "category_quality": {key: round(categories[key] * 100.0, 1) for key in categories},
        "active_categories": active,
        "contributors": contributors,
    }
