"""Deterministic institutional confidence categories for TradeIQ v3.0.

This module does not create trades. It normalizes evidence already produced by
market structure, GEX, liquidity, momentum, volume and session services into a
transparent 100-point score.
"""
from __future__ import annotations

from typing import Mapping

CATEGORY_WEIGHTS: dict[str, float] = {
    "trend": 20.0,
    "structure": 20.0,
    "gex": 20.0,
    "liquidity": 15.0,
    "momentum": 10.0,
    "volume": 10.0,
    "session": 5.0,
}


def _quality(value: bool | float | int | None) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def grade_for_score(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 85:
        return "A"
    if score >= 78:
        return "B+"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "AVOID"


def calculate_institutional_confidence(evidence: Mapping[str, bool | float | int | None]) -> tuple[float, dict[str, float], str]:
    """Return total score, awarded category points and a human-readable grade."""
    components: dict[str, float] = {}
    for name, weight in CATEGORY_WEIGHTS.items():
        components[name] = round(weight * _quality(evidence.get(name)), 1)
    score = round(sum(components.values()), 1)
    return score, components, grade_for_score(score)
