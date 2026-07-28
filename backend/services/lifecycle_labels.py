"""Human-facing lifecycle stage labels for TradeIQ.

This module never changes engine behaviour. It only maps the existing
`order_state` (and a few supporting fields) onto the vocabulary the trader
actually wants to read: SCANNING, AT_LOCATION, MONITORING, LIMIT_READY,
FILLED, MANAGING, CANCELLED, INVALIDATED, EXPIRED. The detailed internal
`order_state` and `last_transition_reason` remain the authoritative "why" and
are unchanged; this is purely an additive display layer.
"""
from __future__ import annotations

from typing import Any, Mapping


DISPLAY_STAGES = (
    "SCANNING", "AT_LOCATION", "MONITORING", "LIMIT_READY",
    "FILLED", "MANAGING", "CANCELLED", "INVALIDATED", "EXPIRED",
)


def display_stage(setup: Any) -> str:
    order_state = getattr(setup, "order_state", None)
    if order_state is None and isinstance(setup, Mapping):
        order_state = setup.get("order_state")
    order_state = str(order_state or "PREVIEW_ONLY")

    if order_state == "WATCHING":
        return "MONITORING"
    if order_state == "WAITING_FOR_LIMIT":
        return "LIMIT_READY"
    if order_state == "FILLED":
        return "FILLED"
    if order_state == "TP1_HIT":
        return "MANAGING"
    if order_state in {"STOPPED", "TP2_HIT"}:
        return "CANCELLED"
    if order_state in {"EXPIRED", "UNCONFIRMED_TOUCH"}:
        return "EXPIRED"
    if order_state == "INVALIDATED":
        return "INVALIDATED"

    # PREVIEW_ONLY (or any unrecognized state defaults to it): distinguish a
    # bare scan from price actually sitting inside a real location.
    quality_stage = getattr(setup, "quality_stage", None)
    signals = getattr(setup, "signals", None)
    if quality_stage is None and isinstance(setup, Mapping):
        quality_stage = setup.get("quality_stage")
        signals = setup.get("signals")
    signals = signals if isinstance(signals, Mapping) else {}
    at_location = bool(
        quality_stage in {"LOCATION_ONLY", "CONFIRMED_NO_EXECUTION"}
        or signals.get("market_map_actionable_location")
    )
    return "AT_LOCATION" if at_location else "SCANNING"
