from datetime import datetime, timedelta, timezone
from math import exp
from uuid import uuid4

from backend.core.config import settings
from backend.models.schemas import GexSummary, TradeSetup
from backend.services.databento_gex import gex_service
from backend.services.market_data import market_data_service, rth_candles
from backend.services.timeframes import aggregate_candles
from engine.confidence import DEFAULT_WEIGHTS, calculate_confidence
from engine.confluence_cluster import find_confluence_cluster
from engine.fib_ote import calculate_fib_levels, ote_zone
from engine.gex import OptionPosition, derive_gex_summary_from_positions
from engine.market_structure import analyze_market_structure
from engine.risk_engine import build_trade_levels
from engine.supply_demand import detect_supply_demand


def average_true_range(candles, period: int = 14) -> float:
    if len(candles) < 2:
        return 12.0
    values = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        values.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))
    sample = values[-period:]
    return sum(sample) / len(sample) if sample else 12.0


def calculate_vwap(candles) -> float:
    if not candles:
        return 0.0
    volume = sum(c.volume for c in candles) or 1
    return sum(((c.high + c.low + c.close) / 3) * c.volume for c in candles) / volume


def standard_deviation_levels(candles, vwap: float) -> tuple[float, float]:
    if not candles:
        return vwap, vwap
    volume = sum(c.volume for c in candles) or 1
    variance = sum(c.volume * (c.close - vwap) ** 2 for c in candles) / volume
    sigma = variance ** .5
    return vwap - sigma, vwap + sigma


def mock_option_chain(price: float) -> list[OptionPosition]:
    positions: list[OptionPosition] = []
    center = round(price / 25) * 25
    for strike in range(int(center - 300), int(center + 325), 25):
        distance = abs(strike - center)
        base_oi = int(650 + 5100 * exp(-distance / 155))
        iv = .185 + distance / max(price, 1) * 2.25
        call_boost = 2.85 if strike == center + 75 else 1.75 if strike == center + 50 else 1.0
        put_boost = 3.0 if strike == center - 100 else 1.85 if strike == center - 75 else 1.0
        positions.extend([
            OptionPosition(strike, 7 / 365, "CALL", int(base_oi * call_boost), iv),
            OptionPosition(strike, 7 / 365, "PUT", int(base_oi * put_boost), iv * 1.035),
        ])
    return positions


def proximity_score(price: float, low: float, high: float, tolerance: float) -> float:
    if low <= price <= high:
        return 1.0
    return max(0.0, 1.0 - min(abs(price - low), abs(price - high)) / max(tolerance, .25))


def _direction_from_structure(structure: dict, current_price: float, gex: GexSummary) -> str:
    if structure["trend"] == "BULLISH":
        return "LONG"
    if structure["trend"] == "BEARISH":
        return "SHORT"
    return "LONG" if current_price >= gex.gamma_flip else "SHORT"


def build_candidate_setup(candles_override=None) -> TradeSetup:
    base_candles = candles_override or market_data_service.snapshot()
    if not base_candles:
        raise RuntimeError("No market candles are available.")
    candles_5m = aggregate_candles(base_candles, 5)
    candles_15m = aggregate_candles(base_candles, 15)
    candles_60m = aggregate_candles(base_candles, 60)
    current_price = base_candles[-1].close

    structure = analyze_market_structure(candles_5m)
    zones = (
        detect_supply_demand(candles_5m, timeframe="5m", lookback=90)
        + detect_supply_demand(candles_15m, timeframe="15m", lookback=70)
        + detect_supply_demand(candles_60m, timeframe="1H", lookback=45)
    )
    zones = sorted(zones, key=lambda z: (z.fresh, z.strength, z.created_at or base_candles[0].time), reverse=True)[:12]

    gex = gex_service.get_summary(current_price)
    if gex is None:
        positions = mock_option_chain(current_price)
        raw = derive_gex_summary_from_positions(current_price, positions, flip_range_points=450)
        raw.update({"source": "simulated-fallback", "updated_at": datetime.now(timezone.utc), "contract_count": len(positions), "expiry_count": 1, "is_estimate": True})
        gex = GexSummary(**raw)

    direction = _direction_from_structure(structure, current_price, gex)
    swing_low, swing_high = structure["swing_low"], structure["swing_high"]
    if swing_high <= swing_low:
        swing_high = swing_low + 20
    fib_points = calculate_fib_levels(swing_low, swing_high, direction)
    fib_levels = [{"ratio": p.ratio, "price": p.price, "label": p.label} for p in fib_points]
    ote_low, ote_high = ote_zone(swing_low, swing_high, direction)
    ideal_ote = next(p.price for p in fib_points if abs(p.ratio - .705) < .001)
    atr = average_true_range(candles_5m)

    cluster = find_confluence_cluster(direction, ote_low, ote_high, zones, gex, atr, current_price, settings.cluster_tolerance_atr)
    session = rth_candles(base_candles)
    session_high, session_low = max(c.high for c in session), min(c.low for c in session)
    vwap = calculate_vwap(session)
    std_low, std_high = standard_deviation_levels(session, vwap)

    direction_sweep = structure["sell_side_sweep"] if direction == "LONG" else structure["buy_side_sweep"]
    direction_displacement = structure["bullish_displacement"] if direction == "LONG" else structure["bearish_displacement"]
    direction_fvg = structure["bullish_fvg"] if direction == "LONG" else structure["bearish_fvg"]
    ordered_sequence = structure["bullish_sequence"] if direction == "LONG" else structure["bearish_sequence"]
    trend_alignment = structure["bullish_ema_aligned"] if direction == "LONG" else structure["bearish_ema_aligned"]

    levels = build_trade_levels(
        direction=direction, current_price=current_price, ote_low=ote_low, ote_high=ote_high,
        ideal_ote=ideal_ote, zones=zones, atr=atr, cluster=cluster, gex=gex,
        previous_liquidity_high=structure["previous_liquidity_high"],
        previous_liquidity_low=structure["previous_liquidity_low"],
        session_high=session_high, session_low=session_low,
        sweep_price=structure["sweep_price"] if direction_sweep else None,
        tick_size=settings.nq_tick_size,
    )

    analysis_price = levels["entry"] if levels["entry"] is not None else current_price
    selected_zone = cluster.zone
    zone_quality = 0.0
    if selected_zone:
        freshness = 1.0 if selected_zone.fresh else max(.35, .85 - selected_zone.touches * .14)
        zone_quality = selected_zone.strength / 5 * freshness

    gex_alignment = (direction == "LONG" and current_price >= gex.gamma_flip) or (direction == "SHORT" and current_price <= gex.gamma_flip)
    vwap_alignment = (direction == "LONG" and current_price >= vwap) or (direction == "SHORT" and current_price <= vwap)
    std_score = max(
        proximity_score(analysis_price, std_low - atr * .25, std_low + atr * .25, atr * 2),
        proximity_score(analysis_price, std_high - atr * .25, std_high + atr * .25, atr * 2),
    )
    ote_score = proximity_score(analysis_price, ote_low, ote_high, atr * 1.5)
    displacement_quality = 1.0 if ordered_sequence else .75 if direction_displacement and direction_fvg else .45 if direction_displacement else 0.0
    ranges = [c.high - c.low for c in candles_5m[-30:]]
    normal_range = sum(ranges) / len(ranges) if ranges else atr
    volatility_quality = max(0.0, min(1.0, normal_range / max(atr, .25)))
    risk_quality = 1.0 if levels["entry_valid"] and not levels["blocked_by_near_target"] and (levels["tp2_r"] or 0) >= 2 else 0.0

    flags = {
        "trend_alignment": trend_alignment,
        "gex_alignment": gex_alignment,
        "liquidity_sweep": direction_sweep,
        "displacement": displacement_quality,
        "ote_overlap": ote_score,
        "supply_demand": zone_quality,
        "gex_ote_zone_cluster": cluster.score,
        "std_dev_confluence": std_score,
        "vwap_alignment": vwap_alignment,
        "session_volatility": volatility_quality,
        "risk_reward": risk_quality,
    }
    confidence, components = calculate_confidence(flags)
    nearest_wall = gex.call_wall if direction == "LONG" else gex.put_wall
    signals = {
        "trend_alignment": bool(trend_alignment), "gex_alignment": bool(gex_alignment),
        "liquidity_sweep": bool(direction_sweep), "displacement": bool(direction_displacement),
        "directional_fvg": bool(direction_fvg), "ordered_sequence": bool(ordered_sequence),
        "sequence_detail": structure["sequence_detail"],
        "ote_overlap": ote_score >= .72, "supply_demand": zone_quality >= .65,
        "gex_ote_zone_cluster": cluster.score >= settings.cluster_min_score,
        "gex_inside_cluster": cluster.gex_inside_cluster,
        "std_dev_confluence": std_score >= .7, "vwap_alignment": bool(vwap_alignment),
        "valid_limit": bool(levels["entry_valid"]), "target_not_blocked": not levels["blocked_by_near_target"],
        "approaching_wall": abs(nearest_wall - current_price) <= atr * 5,
        "rth_session_bars": len(session),
    }
    mandatory = all([
        trend_alignment, gex_alignment, cluster.score >= settings.cluster_min_score,
        levels["entry_valid"], not levels["blocked_by_near_target"],
        ordered_sequence or (direction_sweep and direction_displacement),
        (levels["tp2_r"] or 0) >= 2.0,
    ])
    actionable = confidence >= settings.setup_actionable_score and mandatory

    rationale = []
    if trend_alignment: rationale.append(f"The 9/21/55 EMA structure is {direction.lower()}-aligned.")
    if gex_alignment: rationale.append("Price is on the supportive side of the gamma flip.")
    if ordered_sequence: rationale.append("A recent sweep → displacement → FVG sequence is confirmed in the trade direction.")
    elif direction_sweep or direction_displacement: rationale.append("Directional liquidity/displacement is present, but the full ordered sequence is incomplete.")
    if cluster.score >= settings.cluster_min_score:
        zone_name = f"{cluster.zone.timeframe} {cluster.zone.kind.lower()}" if cluster.zone else "zone"
        rationale.append(f"OTE, {zone_name}, and {cluster.gex_type or 'GEX'} cluster around {cluster.low:,.2f}–{cluster.high:,.2f}.")
    if levels["blocked_by_near_target"]: rationale.append("A nearby market level blocks sufficient reward; preview only.")
    if not levels["entry_valid"]: rationale.append("The proposed entry is not a valid resting limit relative to current price.")
    if levels["target_sources"]: rationale.append(f"TP1 uses {levels['target_sources']['tp1']}; TP2 uses {levels['target_sources']['tp2']}.")
    if not rationale: rationale.append("The engine is scanning for a stronger multi-factor setup.")

    status = "WAITING_FOR_LIMIT" if actionable else "DEVELOPING" if confidence >= 55 and levels["entry_valid"] else "SCANNING"
    now = datetime.now(timezone.utc)
    return TradeSetup(
        setup_id=f"preview-{uuid4()}", timestamp=now,
        valid_until=now + timedelta(minutes=settings.setup_expiry_minutes), direction=direction,
        confidence=confidence, confidence_components=components,
        confidence_maximums={k: float(v) for k, v in DEFAULT_WEIGHTS.items()}, signals=signals,
        actionable=actionable, entry_valid=bool(levels["entry_valid"]),
        order_state="ARMED" if actionable else "PREVIEW_ONLY",
        entry=levels["entry"], stop_loss=levels["stop_loss"], take_profit_1=levels["take_profit_1"],
        take_profit_2=levels["take_profit_2"], risk_reward=levels["risk_reward"],
        tp1_r=levels["tp1_r"], tp2_r=levels["tp2_r"], target_sources=levels["target_sources"],
        status=status, rationale=rationale, gex=gex, zones=zones, fib_levels=fib_levels,
        atr=round(atr, 2), vwap=round(vwap, 2), standard_deviation_high=round(std_high, 2), standard_deviation_low=round(std_low, 2),
        cluster_score=round(cluster.score, 3), cluster_low=cluster.low, cluster_high=cluster.high,
        cluster_gex_level=cluster.gex_level, cluster_gex_type=cluster.gex_type,
        selected_zone_low=selected_zone.low if selected_zone else None,
        selected_zone_high=selected_zone.high if selected_zone else None,
        selected_zone_timeframe=selected_zone.timeframe if selected_zone else None,
    )


def build_current_setup() -> TradeSetup:
    from backend.services.trade_engine import trade_engine_service
    current = trade_engine_service.current_setup()
    return current or build_candidate_setup()
