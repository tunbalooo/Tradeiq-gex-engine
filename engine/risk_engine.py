from dataclasses import dataclass

from backend.models.schemas import GexSummary, Zone
from engine.confluence_cluster import ClusterResult


@dataclass(slots=True)
class TargetCandidate:
    price: float
    source: str
    r_multiple: float


def _round_tick(value: float, tick_size: float) -> float:
    return round(round(value / tick_size) * tick_size, 2)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _candidate_r(direction: str, entry: float, stop: float, price: float) -> float:
    risk = abs(entry - stop)
    if risk <= 0:
        return -1.0
    return (price - entry) / risk if direction == "LONG" else (entry - price) / risk


def _collect_targets(
    direction: str,
    entry: float,
    stop: float,
    gex: GexSummary,
    zones: list[Zone],
    previous_liquidity_high: float,
    previous_liquidity_low: float,
    session_high: float,
    session_low: float,
    tick_size: float,
) -> list[TargetCandidate]:
    raw: list[tuple[float, str]] = []
    if direction == "LONG":
        raw.extend([
            (gex.call_wall, "Call Wall"),
            (previous_liquidity_high, "Previous Buy-Side Liquidity"),
            (session_high, "Session High"),
        ])
        raw.extend((level.price, level.type) for level in gex.levels if level.price > entry)
        raw.extend((zone.low, f"{zone.timeframe} Supply Zone") for zone in zones if zone.kind == "SUPPLY" and zone.low > entry)
    else:
        raw.extend([
            (gex.put_wall, "Put Wall"),
            (previous_liquidity_low, "Previous Sell-Side Liquidity"),
            (session_low, "Session Low"),
        ])
        raw.extend((level.price, level.type) for level in gex.levels if level.price < entry)
        raw.extend((zone.high, f"{zone.timeframe} Demand Zone") for zone in zones if zone.kind == "DEMAND" and zone.high < entry)

    unique: dict[float, TargetCandidate] = {}
    for price, source in raw:
        if price is None:
            continue
        price = _round_tick(float(price), tick_size)
        if direction == "LONG" and price <= entry:
            continue
        if direction == "SHORT" and price >= entry:
            continue
        r_multiple = _candidate_r(direction, entry, stop, price)
        if r_multiple <= 0:
            continue
        existing = unique.get(price)
        candidate = TargetCandidate(price=price, source=source, r_multiple=r_multiple)
        if existing is None or candidate.r_multiple < existing.r_multiple:
            unique[price] = candidate
    return sorted(unique.values(), key=lambda item: item.r_multiple)


def build_trade_levels(
    direction: str,
    current_price: float,
    ote_low: float,
    ote_high: float,
    ideal_ote: float,
    zones: list[Zone],
    atr: float,
    cluster: ClusterResult,
    gex: GexSummary,
    previous_liquidity_high: float,
    previous_liquidity_low: float,
    session_high: float,
    session_low: float,
    sweep_price: float | None = None,
    tick_size: float = 0.25,
) -> dict:
    direction = direction.upper()
    if direction not in {"LONG", "SHORT"}:
        return {
            "entry": None, "stop_loss": None, "take_profit_1": None,
            "take_profit_2": None, "risk_reward": None, "tp1_r": None,
            "tp2_r": None, "entry_valid": False, "blocked_by_near_target": False,
            "target_sources": {},
        }

    selected_zone = cluster.zone
    cluster_low = cluster.low if cluster.low is not None else ote_low
    cluster_high = cluster.high if cluster.high is not None else ote_high
    entry = _clip(ideal_ote, cluster_low, cluster_high)
    buffer = max(tick_size * 2, atr * 0.20)

    if direction == "LONG":
        anchors = [ote_low]
        if selected_zone is not None:
            anchors.append(selected_zone.low)
        if sweep_price is not None:
            anchors.append(sweep_price)
        stop = min(anchors) - buffer
        entry_valid = entry <= current_price - tick_size
    else:
        anchors = [ote_high]
        if selected_zone is not None:
            anchors.append(selected_zone.high)
        if sweep_price is not None:
            anchors.append(sweep_price)
        stop = max(anchors) + buffer
        entry_valid = entry >= current_price + tick_size

    entry = _round_tick(entry, tick_size)
    stop = _round_tick(stop, tick_size)
    risk = abs(entry - stop)
    if risk < tick_size or risk > max(atr * 4.0, 40.0):
        entry_valid = False

    candidates = _collect_targets(
        direction=direction,
        entry=entry,
        stop=stop,
        gex=gex,
        zones=zones,
        previous_liquidity_high=previous_liquidity_high,
        previous_liquidity_low=previous_liquidity_low,
        session_high=session_high,
        session_low=session_low,
        tick_size=tick_size,
    )

    nearest_barrier = candidates[0] if candidates else None
    blocked_by_near_target = nearest_barrier is not None and nearest_barrier.r_multiple < 1.0

    tp1_candidate = next((candidate for candidate in candidates if candidate.r_multiple >= 1.0), None)
    if tp1_candidate is None:
        tp1_price = entry + risk * 2.0 if direction == "LONG" else entry - risk * 2.0
        tp1_candidate = TargetCandidate(_round_tick(tp1_price, tick_size), "2R Fallback", 2.0)

    tp2_candidate = next(
        (
            candidate for candidate in candidates
            if candidate.price != tp1_candidate.price
            and candidate.r_multiple >= max(2.0, tp1_candidate.r_multiple + 0.25)
        ),
        None,
    )
    if tp2_candidate is None:
        fallback_r = 2.0 if tp1_candidate.r_multiple < 2.0 else max(3.0, tp1_candidate.r_multiple + 1.0)
        tp2_price = entry + risk * fallback_r if direction == "LONG" else entry - risk * fallback_r
        tp2_candidate = TargetCandidate(_round_tick(tp2_price, tick_size), f"{fallback_r:.1f}R Fallback", fallback_r)

    return {
        "entry": entry,
        "stop_loss": stop,
        "take_profit_1": tp1_candidate.price,
        "take_profit_2": tp2_candidate.price,
        "risk_reward": round(tp2_candidate.r_multiple, 2),
        "tp1_r": round(tp1_candidate.r_multiple, 2),
        "tp2_r": round(tp2_candidate.r_multiple, 2),
        "entry_valid": bool(entry_valid),
        "blocked_by_near_target": bool(blocked_by_near_target),
        "target_sources": {
            "tp1": tp1_candidate.source,
            "tp2": tp2_candidate.source,
            "nearest_barrier": nearest_barrier.source if nearest_barrier else "None",
        },
    }
