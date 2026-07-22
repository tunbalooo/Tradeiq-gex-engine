"""Ranked institutional level map for TradeIQ.

The live chart can contain many useful references: GEX walls/nodes, supply and
Demand zones, OTE/Fibonacci levels, VWAP/value bands and session liquidity. This
module groups nearby references into a small auditable ladder. It does not create
a trade by itself. The existing model-confirmation, execution and risk engines
remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from backend.core.config import settings
from backend.models.schemas import (
    Candle,
    FibLevel,
    GexSummary,
    InstitutionalMarketMap,
    MarketMapCluster,
    MarketMapContributor,
    Zone,
)


GROUP_WEIGHTS = {
    "GEX": 24.0,
    "ZONE": 24.0,
    "RETRACEMENT": 17.0,
    "LIQUIDITY": 20.0,
    "VALUE": 15.0,
}

STATE_PRIORITY = {
    "REJECTING": 5,
    "TESTING": 4,
    "APPROACHING": 3,
    "DISTANT": 1,
    "ACCEPTING": 0,
}


@dataclass(slots=True)
class _Atom:
    label: str
    source_group: str
    role: str
    low: float
    high: float
    quality: float
    fresh: bool = True
    timeframe: str | None = None

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    return number


def _dynamic_role(price: float, current_price: float) -> str:
    return "SUPPORT" if price <= current_price else "RESISTANCE"


def _point_atom(
    label: str,
    source_group: str,
    price: object,
    role: str,
    quality: float,
    *,
    tick_size: float,
    fresh: bool = True,
    timeframe: str | None = None,
) -> _Atom | None:
    value = _finite(price)
    if value is None:
        return None
    half = max(float(tick_size), 1e-9)
    return _Atom(
        label=label,
        source_group=source_group,
        role=role,
        low=value - half,
        high=value + half,
        quality=max(0.0, min(1.0, float(quality))),
        fresh=fresh,
        timeframe=timeframe,
    )


def _zone_quality(zone: Zone) -> float:
    freshness = 1.0 if zone.fresh else max(0.35, 0.88 - zone.touches * 0.16)
    timeframe_boost = {"4H": 1.0, "1H": 0.96, "15m": 0.90, "5m": 0.84}.get(zone.timeframe, 0.82)
    departure = max(0.0, min(1.0, float(zone.displacement_score or 0.0) / 1.25))
    return max(0.0, min(1.0, (zone.strength / 5.0 * 0.62 + departure * 0.20 + freshness * 0.18) * timeframe_boost))


def _collect_atoms(
    *,
    current_price: float,
    tick_size: float,
    gex: GexSummary,
    zones: list[Zone],
    fib_levels: list[FibLevel],
    vwap: float,
    std_low: float,
    std_high: float,
    session_low: float,
    session_high: float,
    previous_liquidity_low: float | None,
    previous_liquidity_high: float | None,
) -> list[_Atom]:
    atoms: list[_Atom] = []

    specials = [
        ("Gamma Resistance / Call Wall", "GEX", gex.call_wall, "RESISTANCE", 1.00),
        ("Gamma Support / Put Wall", "GEX", gex.put_wall, "SUPPORT", 1.00),
        ("Gamma Resistance", "GEX", gex.gamma_resistance, "RESISTANCE", 0.90),
        ("Gamma Support", "GEX", gex.gamma_support, "SUPPORT", 0.90),
        ("Gamma Flip", "GEX", gex.gamma_flip, _dynamic_role(gex.gamma_flip, current_price), 0.82),
        ("Maximum Pain", "GEX", gex.max_pain, _dynamic_role(float(gex.max_pain or current_price), current_price), 0.66),
    ]
    for label, group, price, role, quality in specials:
        atom = _point_atom(label, group, price, role, quality, tick_size=tick_size, fresh=not gex.is_estimate)
        if atom:
            atoms.append(atom)

    for level in (gex.levels or [])[:8]:
        strength = max(0.0, min(1.0, float(level.strength or 0) / 5.0))
        quality = 0.48 + strength * 0.34
        atom = _point_atom(
            level.type or "GEX Node",
            "GEX",
            level.price,
            _dynamic_role(float(level.price), current_price),
            quality,
            tick_size=tick_size,
            fresh=not gex.is_estimate,
        )
        if atom:
            atoms.append(atom)

    for zone in zones:
        if zone.invalidated:
            continue
        atoms.append(_Atom(
            label=f"{zone.timeframe} {zone.kind.title()}",
            source_group="ZONE",
            role="SUPPORT" if zone.kind == "DEMAND" else "RESISTANCE",
            low=float(zone.low),
            high=float(zone.high),
            quality=_zone_quality(zone),
            fresh=bool(zone.fresh),
            timeframe=zone.timeframe,
        ))

    ratio_quality = {0.50: 0.58, 0.618: 0.74, 0.705: 0.82, 0.786: 0.72}
    for fib in fib_levels:
        ratio = min(ratio_quality, key=lambda item: abs(item - float(fib.ratio)))
        if abs(float(fib.ratio) - ratio) > 0.004:
            continue
        atom = _point_atom(
            fib.label or f"Fib {ratio:.3f}",
            "RETRACEMENT",
            fib.price,
            _dynamic_role(float(fib.price), current_price),
            ratio_quality[ratio],
            tick_size=tick_size,
        )
        if atom:
            atoms.append(atom)

    value_levels = [
        ("VWAP", vwap, _dynamic_role(vwap, current_price), 0.76),
        ("Value +1σ", std_high, "RESISTANCE", 0.58),
        ("Value -1σ", std_low, "SUPPORT", 0.58),
    ]
    for label, price, role, quality in value_levels:
        atom = _point_atom(label, "VALUE", price, role, quality, tick_size=tick_size)
        if atom:
            atoms.append(atom)

    liquidity_levels = [
        ("Session High", session_high, "RESISTANCE", 0.80),
        ("Session Low", session_low, "SUPPORT", 0.80),
        ("Previous Buy-Side Liquidity", previous_liquidity_high, "RESISTANCE", 0.86),
        ("Previous Sell-Side Liquidity", previous_liquidity_low, "SUPPORT", 0.86),
    ]
    for label, price, role, quality in liquidity_levels:
        atom = _point_atom(label, "LIQUIDITY", price, role, quality, tick_size=tick_size)
        if atom:
            atoms.append(atom)

    # Remove exact/near-exact duplicates from the same source group. Special GEX
    # references retain the stronger quality while related raw nodes are capped.
    deduped: list[_Atom] = []
    duplicate_tolerance = max(tick_size * 2, 1e-9)
    for atom in sorted(atoms, key=lambda item: item.quality, reverse=True):
        duplicate = next((
            existing for existing in deduped
            if existing.source_group == atom.source_group
            and existing.role == atom.role
            and abs(existing.midpoint - atom.midpoint) <= duplicate_tolerance
        ), None)
        if duplicate is None:
            deduped.append(atom)
    return deduped


def _interval_gap(left: _Atom, right: _Atom) -> float:
    if left.high >= right.low and right.high >= left.low:
        return 0.0
    return max(right.low - left.high, left.low - right.high, 0.0)


def _group_atoms(atoms: Iterable[_Atom], tolerance: float) -> list[list[_Atom]]:
    clusters: list[list[_Atom]] = []
    for role in ("SUPPORT", "RESISTANCE"):
        ordered = sorted((item for item in atoms if item.role == role), key=lambda item: item.midpoint)
        for atom in ordered:
            if not clusters or clusters[-1][0].role != role:
                clusters.append([atom])
                continue
            current = clusters[-1]
            cluster_low = min(item.low for item in current)
            cluster_high = max(item.high for item in current)
            proxy = _Atom("cluster", current[0].source_group, role, cluster_low, cluster_high, 1.0)
            if _interval_gap(proxy, atom) <= tolerance:
                current.append(atom)
            else:
                clusters.append([atom])
    return clusters


def _distance_to_range(price: float, low: float, high: float) -> float:
    if low <= price <= high:
        return 0.0
    return min(abs(price - low), abs(price - high))


def _cluster_state(
    role: str,
    low: float,
    high: float,
    current_price: float,
    atr: float,
    tick_size: float,
    candles: list[Candle],
) -> tuple[str, bool]:
    touch_pad = max(tick_size * 2, atr * 0.04)
    reaction = max(tick_size * 4, atr * 0.12)
    acceptance = max(tick_size * 2, atr * 0.05)
    recent = candles[-5:]
    closes = [float(item.close) for item in recent]
    touched = any(item.low <= high + touch_pad and item.high >= low - touch_pad for item in recent)
    distance = _distance_to_range(current_price, low, high)

    if role == "SUPPORT":
        accepted = len(closes) >= 2 and closes[-1] < low - acceptance and closes[-2] < low - acceptance
        if accepted:
            return "ACCEPTING", True
        if low - touch_pad <= current_price <= high + touch_pad:
            return "TESTING", False
        if touched and current_price >= high + reaction:
            return "REJECTING", False
    else:
        accepted = len(closes) >= 2 and closes[-1] > high + acceptance and closes[-2] > high + acceptance
        if accepted:
            return "ACCEPTING", True
        if low - touch_pad <= current_price <= high + touch_pad:
            return "TESTING", False
        if touched and current_price <= low - reaction:
            return "REJECTING", False

    if distance <= max(atr * settings.market_map_approach_atr, tick_size * 16):
        return "APPROACHING", False
    return "DISTANT", False


def _build_cluster(
    atoms: list[_Atom],
    *,
    index: int,
    current_price: float,
    atr: float,
    tick_size: float,
    candles: list[Candle],
) -> MarketMapCluster:
    role = atoms[0].role
    low = min(item.low for item in atoms)
    high = max(item.high for item in atoms)
    group_quality: dict[str, float] = {}
    group_freshness: dict[str, float] = {}
    for atom in atoms:
        group_quality[atom.source_group] = max(group_quality.get(atom.source_group, 0.0), atom.quality)
        group_freshness[atom.source_group] = max(group_freshness.get(atom.source_group, 0.0), 1.0 if atom.fresh else 0.45)

    active_weight = sum(GROUP_WEIGHTS[group] for group in group_quality)
    weighted_quality = sum(GROUP_WEIGHTS[group] * quality for group, quality in group_quality.items())
    normalized_quality = weighted_quality / active_weight * 100.0 if active_weight else 0.0
    independent = len(group_quality)
    breadth_bonus = {1: 4.0, 2: 12.0, 3: 18.0, 4: 23.0, 5: 27.0}.get(independent, 27.0)
    density_bonus = min(6.0, max(0, len(atoms) - independent) * 1.5)
    score = min(100.0, normalized_quality * 0.70 + breadth_bonus + density_bonus)
    freshness = (
        sum(GROUP_WEIGHTS[group] * group_freshness[group] for group in group_quality) / active_weight * 100.0
        if active_weight else 0.0
    )
    state, accepted = _cluster_state(role, low, high, current_price, atr, tick_size, candles)
    distance = _distance_to_range(current_price, low, high)
    if score >= 88 and independent >= 3:
        tier = "MAJOR"
    elif score >= 78 and independent >= 2:
        tier = "STRONG"
    elif score >= 68:
        tier = "QUALIFIED"
    else:
        tier = "CONTEXT"
    actionable_location = bool(
        independent >= 2
        and score >= float(settings.market_map_min_actionable_score)
        and state in {"APPROACHING", "TESTING", "REJECTING"}
        and not accepted
    )
    display_priority = (
        STATE_PRIORITY.get(state, 0) * 20.0
        + score
        - min(50.0, distance / max(atr, tick_size) * 10.0)
    )
    contributors = [
        MarketMapContributor(
            label=item.label,
            source_group=item.source_group,
            role=item.role,
            low=round(item.low, 4),
            high=round(item.high, 4),
            midpoint=round(item.midpoint, 4),
            quality=round(item.quality, 3),
            fresh=item.fresh,
            timeframe=item.timeframe,
        )
        for item in sorted(atoms, key=lambda item: (-item.quality, item.label))
    ]
    return MarketMapCluster(
        cluster_id=f"{role.lower()}-{index}-{round((low + high) / 2.0, 4)}",
        role=role,
        low=round(low, 4),
        high=round(high, 4),
        midpoint=round((low + high) / 2.0, 4),
        score=round(score, 1),
        tier=tier,
        state=state,
        distance_points=round(distance, 4),
        distance_atr=round(distance / max(atr, tick_size), 3),
        independent_categories=independent,
        source_groups=sorted(group_quality),
        contributors=contributors,
        freshness=round(freshness, 1),
        actionable_location=actionable_location,
        accepted_through=accepted,
        display_priority=round(display_priority, 1),
    )


def _same_cluster(left: MarketMapCluster | None, right: MarketMapCluster | None) -> bool:
    return bool(left and right and left.cluster_id == right.cluster_id)


def build_institutional_market_map(
    *,
    current_price: float,
    atr: float,
    tick_size: float,
    candles: list[Candle],
    gex: GexSummary,
    zones: list[Zone],
    fib_levels: list[FibLevel],
    vwap: float,
    std_low: float,
    std_high: float,
    session_low: float,
    session_high: float,
    previous_liquidity_low: float | None,
    previous_liquidity_high: float | None,
    direction: str,
) -> InstitutionalMarketMap:
    atr = max(float(atr or 0.0), float(tick_size) * 8)
    tolerance = max(
        atr * float(settings.market_map_cluster_tolerance_atr),
        float(tick_size) * int(settings.market_map_cluster_tolerance_ticks),
    )
    atoms = _collect_atoms(
        current_price=current_price,
        tick_size=tick_size,
        gex=gex,
        zones=zones,
        fib_levels=fib_levels,
        vwap=vwap,
        std_low=std_low,
        std_high=std_high,
        session_low=session_low,
        session_high=session_high,
        previous_liquidity_low=previous_liquidity_low,
        previous_liquidity_high=previous_liquidity_high,
    )
    grouped = _group_atoms(atoms, tolerance)
    clusters = [
        _build_cluster(
            items,
            index=index,
            current_price=current_price,
            atr=atr,
            tick_size=tick_size,
            candles=candles,
        )
        for index, items in enumerate(grouped, start=1)
    ]
    visible = [
        item for item in clusters
        if item.score >= float(settings.market_map_min_display_score)
    ]
    supports = sorted(
        (
            item for item in visible
            if item.role == "SUPPORT"
            and not item.accepted_through
            and item.high <= current_price + tolerance
        ),
        key=lambda item: item.distance_points,
    )
    resistances = sorted(
        (
            item for item in visible
            if item.role == "RESISTANCE"
            and not item.accepted_through
            and item.low >= current_price - tolerance
        ),
        key=lambda item: item.distance_points,
    )
    nearest_support = supports[0] if supports else None
    nearest_resistance = resistances[0] if resistances else None

    direction = str(direction or "NONE").upper()
    desired_active_role = "SUPPORT" if direction == "LONG" else "RESISTANCE" if direction == "SHORT" else None
    nearby = [
        item for item in visible
        if item.actionable_location
        and not item.accepted_through
        and (desired_active_role is None or item.role == desired_active_role)
        and item.distance_points <= atr * 1.25
        and item.state in {"APPROACHING", "TESTING", "REJECTING"}
    ]
    active_cluster = max(nearby, key=lambda item: item.display_priority, default=None)
    if direction == "LONG":
        opposing = nearest_resistance
    elif direction == "SHORT":
        opposing = nearest_support
    elif active_cluster and active_cluster.role == "SUPPORT":
        opposing = nearest_resistance
    elif active_cluster and active_cluster.role == "RESISTANCE":
        opposing = nearest_support
    else:
        opposing = None
    if _same_cluster(active_cluster, opposing):
        opposing = nearest_resistance if active_cluster and active_cluster.role == "SUPPORT" else nearest_support

    # Keep a compact price ladder, preserving the closest levels on both sides and
    # the active/opposing clusters even when their raw score rank is lower.
    ordered = sorted(visible, key=lambda item: (item.distance_points, -item.score))
    selected: list[MarketMapCluster] = []
    for item in [active_cluster, opposing, nearest_support, nearest_resistance, *ordered]:
        if item is None or any(existing.cluster_id == item.cluster_id for existing in selected):
            continue
        selected.append(item)
        if len(selected) >= int(settings.market_map_max_ladder_clusters):
            break
    selected = sorted(selected, key=lambda item: item.midpoint, reverse=True)

    return InstitutionalMarketMap(
        generated_at=datetime.now(timezone.utc),
        current_price=round(float(current_price), 4),
        tolerance_points=round(tolerance, 4),
        active_cluster=active_cluster,
        opposing_cluster=opposing,
        nearest_support=nearest_support,
        nearest_resistance=nearest_resistance,
        ladder=selected,
    )
