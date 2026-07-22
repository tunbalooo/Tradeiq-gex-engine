"""Independent-evidence institutional confluence cluster scoring."""
from __future__ import annotations

from typing import Any

from backend.models.schemas import EntryModelScore


def _q(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def build_cluster_score(signals: dict[str, Any], ranking: list[EntryModelScore], cluster_score: float) -> dict[str, Any]:
    # Related labels are grouped so OTE/Fib and Supply/Order Block cannot inflate
    # confidence by double-counting the same location concept.
    categories = {
        "gex": max(_q(signals.get("gex_alignment")), _q(signals.get("gex_inside_cluster"))),
        "zone": max(_q(signals.get("supply_demand")), _q(signals.get("gex_ote_zone_cluster"))),
        "retracement": max(_q(signals.get("ote_overlap")), _q(signals.get("fib_pullback_touched"))),
        "imbalance": max(_q(signals.get("directional_fvg")), _q(signals.get("inverse_fvg"))),
        "liquidity_structure": max(_q(signals.get("liquidity_sweep")), _q(signals.get("ordered_sequence")), _q(signals.get("displacement"))),
        "trend_value": max(_q(signals.get("trend_alignment")), _q(signals.get("vwap_alignment"))),
    }
    weights = {
        "gex": 18.0, "zone": 18.0, "retracement": 14.0,
        "imbalance": 14.0, "liquidity_structure": 22.0, "trend_value": 14.0,
    }
    score = sum(weights[key] * categories[key] for key in weights)
    # Existing spatial cluster analysis supplies a modest location-quality boost.
    score = min(100.0, score + max(0.0, min(1.0, float(cluster_score or 0.0))) * 8.0)
    active = [key for key, value in categories.items() if value >= 0.6]
    contributors = [item.name for item in ranking if item.eligible and item.score >= 60][:6]
    return {
        "score": round(score, 1),
        "eligible": len(active) >= 3 and score >= 72.0,
        "categories": {key: round(value * weights[key], 1) for key, value in categories.items()},
        "active_categories": active,
        "contributors": contributors,
    }
