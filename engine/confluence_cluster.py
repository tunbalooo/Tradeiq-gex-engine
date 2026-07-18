from dataclasses import dataclass

from backend.models.schemas import GexSummary, Zone


@dataclass(slots=True)
class ClusterResult:
    score: float
    low: float | None
    high: float | None
    zone: Zone | None
    gex_level: float | None
    gex_type: str | None
    direct_ote_zone_overlap: bool
    gex_inside_cluster: bool


def _distance_to_interval(price: float, low: float, high: float) -> float:
    if low <= price <= high:
        return 0.0
    return min(abs(price - low), abs(price - high))


def _gex_candidates(direction: str, gex: GexSummary, current_price: float, tolerance: float) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    direction = direction.upper()
    if direction == "LONG":
        if gex.put_wall <= current_price + tolerance:
            candidates.append(("Put Wall", gex.put_wall))
        if gex.gamma_flip <= current_price + tolerance:
            candidates.append(("Gamma Flip", gex.gamma_flip))
        candidates.extend(
            (level.type, level.price)
            for level in gex.levels
            if (level.gex or 0) > 0 and level.price <= current_price + tolerance
        )
    else:
        if gex.call_wall >= current_price - tolerance:
            candidates.append(("Call Wall", gex.call_wall))
        if gex.gamma_flip >= current_price - tolerance:
            candidates.append(("Gamma Flip", gex.gamma_flip))
        candidates.extend(
            (level.type, level.price)
            for level in gex.levels
            if (level.gex or 0) > 0 and level.price >= current_price - tolerance
        )
    return candidates


def find_confluence_cluster(
    direction: str,
    ote_low: float,
    ote_high: float,
    zones: list[Zone],
    gex: GexSummary,
    atr: float,
    current_price: float,
    tolerance_atr: float = 0.25,
) -> ClusterResult:
    tolerance = max(5.0, atr * tolerance_atr)
    desired_kind = "DEMAND" if direction.upper() == "LONG" else "SUPPLY"
    relevant_zones = [zone for zone in zones if zone.kind == desired_kind and not zone.invalidated]
    candidates = _gex_candidates(direction, gex, current_price, tolerance)

    best = ClusterResult(0.0, None, None, None, None, None, False, False)
    for zone in relevant_zones:
        overlap_low = max(ote_low, zone.low)
        overlap_high = min(ote_high, zone.high)
        direct_overlap = overlap_low <= overlap_high
        if direct_overlap:
            cluster_low, cluster_high = overlap_low, overlap_high
            overlap_quality = 1.0
        else:
            gap = max(zone.low - ote_high, ote_low - zone.high, 0.0)
            if gap > tolerance:
                continue
            cluster_low = min(max(zone.low, ote_low), max(zone.high, ote_high))
            cluster_high = max(min(zone.high, ote_high), min(zone.low, ote_low))
            if cluster_low > cluster_high:
                cluster_low, cluster_high = cluster_high, cluster_low
            overlap_quality = max(0.0, 0.65 * (1.0 - gap / tolerance))

        best_gex_type: str | None = None
        best_gex_level: float | None = None
        best_distance = float("inf")
        for kind, level in candidates:
            distance = _distance_to_interval(level, cluster_low, cluster_high)
            if distance < best_distance:
                best_distance = distance
                best_gex_type = kind
                best_gex_level = level
        gex_quality = 0.0 if best_gex_level is None else max(0.0, 1.0 - best_distance / tolerance)
        gex_inside = best_gex_level is not None and best_distance == 0

        freshness = 1.0 if zone.fresh else max(0.45, 0.85 - zone.touches * 0.12)
        zone_quality = zone.strength / 5 * freshness
        score = 0.40 * overlap_quality + 0.40 * gex_quality + 0.20 * zone_quality

        if score > best.score:
            best = ClusterResult(
                score=round(min(1.0, score), 3),
                low=round(cluster_low, 2),
                high=round(cluster_high, 2),
                zone=zone,
                gex_level=round(best_gex_level, 2) if best_gex_level is not None else None,
                gex_type=best_gex_type,
                direct_ote_zone_overlap=direct_overlap,
                gex_inside_cluster=gex_inside,
            )
    return best
