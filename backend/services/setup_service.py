from datetime import datetime, timedelta, timezone
from math import exp
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.db_models import TradeSetupRecord
from backend.models.schemas import GexSummary, TradeSetup
from backend.services.databento_gex import gex_service
from backend.services.market_data import market_data_service
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
    true_ranges = []
    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    sample = true_ranges[-period:]
    return sum(sample) / len(sample) if sample else 12.0


def calculate_vwap(candles) -> float:
    if not candles:
        return 0.0
    weighted = sum(((c.high + c.low + c.close) / 3) * c.volume for c in candles)
    volume = sum(c.volume for c in candles) or 1
    return weighted / volume


def standard_deviation_levels(candles, vwap: float) -> tuple[float, float]:
    if not candles:
        return vwap, vwap
    volume = sum(c.volume for c in candles) or 1
    variance = sum(c.volume * (c.close - vwap) ** 2 for c in candles) / volume
    sigma = variance**0.5
    return vwap - sigma, vwap + sigma


def mock_option_chain(price: float) -> list[OptionPosition]:
    positions: list[OptionPosition] = []
    center = round(price / 25) * 25
    for strike in range(int(center - 300), int(center + 325), 25):
        distance = abs(strike - center)
        decay = exp(-distance / 155)
        base_oi = int(650 + 5100 * decay)
        expiry = 7 / 365
        iv = 0.185 + distance / max(price, 1) * 2.25
        call_boost = 2.85 if strike == center + 75 else 1.75 if strike == center + 50 else 1.0
        put_boost = 3.0 if strike == center - 100 else 1.85 if strike == center - 75 else 1.0
        call_oi = int(base_oi * call_boost * (1.02 + ((strike // 25) % 5) * 0.025))
        put_oi = int(base_oi * put_boost * (0.98 + ((strike // 25) % 4) * 0.03))
        positions.extend([
            OptionPosition(strike, expiry, "CALL", call_oi, iv),
            OptionPosition(strike, expiry, "PUT", put_oi, iv * 1.035),
        ])
    return positions


def proximity_score(price: float, low: float, high: float, tolerance: float) -> float:
    if low <= price <= high:
        return 1.0
    distance = min(abs(price - low), abs(price - high))
    return max(0.0, 1.0 - distance / max(tolerance, 0.25))


def _direction_from_structure(structure: dict, current_price: float, gex: GexSummary) -> str:
    if structure["trend"] == "BULLISH":
        return "LONG"
    if structure["trend"] == "BEARISH":
        return "SHORT"
    return "LONG" if current_price >= gex.gamma_flip else "SHORT"


def _ideal_ote(fib_points) -> float:
    return next(point.price for point in fib_points if abs(point.ratio - 0.705) < 0.001)


def build_candidate_setup() -> TradeSetup:
    base_candles = market_data_service.snapshot()
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
    zones = sorted(
        zones,
        key=lambda zone: (zone.fresh, zone.strength, zone.created_at or base_candles[0].time),
        reverse=True,
    )[:12]

    gex = gex_service.get_summary(current_price)
    if gex is None:
        positions = mock_option_chain(current_price)
        gex_raw = derive_gex_summary_from_positions(current_price, positions, flip_range_points=450)
        gex_raw.update({
            "source": "simulated-fallback",
            "updated_at": datetime.now(timezone.utc),
            "contract_count": len(positions),
            "expiry_count": 1,
            "is_estimate": True,
        })
        gex = GexSummary(**gex_raw)

    direction = _direction_from_structure(structure, current_price, gex)
    swing_low = structure["swing_low"]
    swing_high = structure["swing_high"]
    if swing_high <= swing_low:
        swing_high = swing_low + 20

    fib_points = calculate_fib_levels(swing_low, swing_high, direction)
    fib_levels = [{"ratio": point.ratio, "price": point.price, "label": point.label} for point in fib_points]
    ote_low, ote_high = ote_zone(swing_low, swing_high, direction)
    ideal_ote = _ideal_ote(fib_points)
    atr = average_true_range(candles_5m)

    cluster = find_confluence_cluster(
        direction=direction,
        ote_low=ote_low,
        ote_high=ote_high,
        zones=zones,
        gex=gex,
        atr=atr,
        current_price=current_price,
        tolerance_atr=settings.cluster_tolerance_atr,
    )

    session_candles = base_candles[-390:]
    session_high = max(candle.high for candle in session_candles)
    session_low = min(candle.low for candle in session_candles)
    vwap = calculate_vwap(session_candles)
    std_low, std_high = standard_deviation_levels(session_candles, vwap)

    direction_sweep = structure["sell_side_sweep"] if direction == "LONG" else structure["buy_side_sweep"]
    direction_displacement = structure["bullish_displacement"] if direction == "LONG" else structure["bearish_displacement"]
    direction_fvg = structure["bullish_fvg"] if direction == "LONG" else structure["bearish_fvg"]
    trend_alignment = structure["bullish_ema_aligned"] if direction == "LONG" else structure["bearish_ema_aligned"]

    levels = build_trade_levels(
        direction=direction,
        current_price=current_price,
        ote_low=ote_low,
        ote_high=ote_high,
        ideal_ote=ideal_ote,
        zones=zones,
        atr=atr,
        cluster=cluster,
        gex=gex,
        previous_liquidity_high=structure["previous_liquidity_high"],
        previous_liquidity_low=structure["previous_liquidity_low"],
        session_high=session_high,
        session_low=session_low,
        sweep_price=structure["sweep_price"] if direction_sweep else None,
        tick_size=settings.nq_tick_size,
    )

    analysis_price = levels["entry"] if levels["entry"] is not None else current_price
    selected_zone = cluster.zone
    zone_quality = 0.0
    if selected_zone is not None:
        freshness = 1.0 if selected_zone.fresh else max(0.45, 0.85 - selected_zone.touches * 0.12)
        zone_quality = selected_zone.strength / 5 * freshness

    gex_alignment = (
        direction == "LONG" and current_price >= gex.gamma_flip
    ) or (
        direction == "SHORT" and current_price <= gex.gamma_flip
    )
    vwap_alignment = (
        direction == "LONG" and current_price >= vwap
    ) or (
        direction == "SHORT" and current_price <= vwap
    )
    std_score = max(
        proximity_score(analysis_price, std_low - atr * 0.25, std_low + atr * 0.25, atr * 2),
        proximity_score(analysis_price, std_high - atr * 0.25, std_high + atr * 0.25, atr * 2),
    )
    ote_score = proximity_score(analysis_price, ote_low, ote_high, atr * 1.5)
    displacement_quality = 1.0 if direction_displacement and direction_fvg else 0.75 if direction_displacement else 0.0

    ranges = [candle.high - candle.low for candle in candles_5m[-30:]]
    normal_range = sum(ranges) / len(ranges) if ranges else atr
    volatility_quality = max(0.0, min(1.0, normal_range / max(atr, 0.25)))
    risk_quality = 1.0 if (
        levels["entry_valid"]
        and not levels["blocked_by_near_target"]
        and (levels["tp2_r"] or 0) >= 2.0
    ) else 0.0

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

    nearest_target_wall = gex.call_wall if direction == "LONG" else gex.put_wall
    approaching_wall = abs(nearest_target_wall - current_price) <= atr * 5
    signals = {
        "trend_alignment": bool(trend_alignment),
        "gex_alignment": bool(gex_alignment),
        "liquidity_sweep": bool(direction_sweep),
        "displacement": bool(direction_displacement),
        "directional_fvg": bool(direction_fvg),
        "ote_overlap": ote_score >= 0.72,
        "supply_demand": zone_quality >= 0.65,
        "gex_ote_zone_cluster": cluster.score >= settings.cluster_min_score,
        "gex_inside_cluster": cluster.gex_inside_cluster,
        "std_dev_confluence": std_score >= 0.7,
        "vwap_alignment": bool(vwap_alignment),
        "valid_limit": bool(levels["entry_valid"]),
        "target_not_blocked": not levels["blocked_by_near_target"],
        "approaching_wall": approaching_wall,
    }

    mandatory = all([
        trend_alignment,
        gex_alignment,
        cluster.score >= settings.cluster_min_score,
        levels["entry_valid"],
        not levels["blocked_by_near_target"],
        direction_sweep or direction_displacement,
        (levels["tp2_r"] or 0) >= 2.0,
    ])
    actionable = confidence >= settings.setup_actionable_score and mandatory

    rationale: list[str] = []
    if trend_alignment:
        rationale.append(f"The 9/21/55 EMA structure is {direction.lower()}-aligned.")
    if gex_alignment:
        rationale.append("Price is on the supportive side of the repriced gamma flip.")
    if direction_sweep:
        sweep_name = "sell-side" if direction == "LONG" else "buy-side"
        rationale.append(f"A directionally valid {sweep_name} liquidity sweep was detected.")
    if direction_displacement:
        rationale.append(f"A {direction.lower()} displacement candle confirms participation.")
    if direction_fvg:
        rationale.append("The displacement also created a directional fair-value gap.")
    if cluster.score >= settings.cluster_min_score:
        zone_name = f"{cluster.zone.timeframe} {cluster.zone.kind.lower()}" if cluster.zone else "zone"
        rationale.append(
            f"OTE, {zone_name}, and {cluster.gex_type or 'GEX'} cluster around "
            f"{cluster.low:,.2f}–{cluster.high:,.2f}."
        )
    if levels["blocked_by_near_target"]:
        rationale.append("A nearby market level blocks enough reward; the setup is preview-only.")
    if not levels["entry_valid"]:
        rationale.append("The calculated price is not a valid resting limit relative to current NQ price.")
    if levels["target_sources"]:
        rationale.append(
            f"TP1 uses {levels['target_sources']['tp1']}; TP2 uses {levels['target_sources']['tp2']}."
        )
    if not rationale:
        rationale.append("The system is scanning; the setup lacks enough independent confluence.")

    if actionable:
        status = "WAITING_FOR_LIMIT"
        order_state = "ARMED"
    elif confidence >= 55 and levels["entry_valid"]:
        status = "DEVELOPING"
        order_state = "PREVIEW_ONLY"
    else:
        status = "SCANNING"
        order_state = "PREVIEW_ONLY"

    now = datetime.now(timezone.utc)
    return TradeSetup(
        setup_id=f"preview-{uuid4()}",
        timestamp=now,
        valid_until=now + timedelta(minutes=settings.setup_expiry_minutes),
        direction=direction,
        confidence=confidence,
        confidence_components=components,
        confidence_maximums={name: float(weight) for name, weight in DEFAULT_WEIGHTS.items()},
        signals=signals,
        actionable=actionable,
        entry_valid=bool(levels["entry_valid"]),
        order_state=order_state,
        entry=levels["entry"],
        stop_loss=levels["stop_loss"],
        take_profit_1=levels["take_profit_1"],
        take_profit_2=levels["take_profit_2"],
        risk_reward=levels["risk_reward"],
        tp1_r=levels["tp1_r"],
        tp2_r=levels["tp2_r"],
        target_sources=levels["target_sources"],
        status=status,
        rationale=rationale,
        gex=gex,
        zones=zones,
        fib_levels=fib_levels,
        atr=round(atr, 2),
        vwap=round(vwap, 2),
        standard_deviation_high=round(std_high, 2),
        standard_deviation_low=round(std_low, 2),
        cluster_score=round(cluster.score, 3),
        cluster_low=cluster.low,
        cluster_high=cluster.high,
        cluster_gex_level=cluster.gex_level,
        cluster_gex_type=cluster.gex_type,
        selected_zone_low=selected_zone.low if selected_zone else None,
        selected_zone_high=selected_zone.high if selected_zone else None,
        selected_zone_timeframe=selected_zone.timeframe if selected_zone else None,
    )


def build_current_setup() -> TradeSetup:
    from backend.services.setup_lifecycle import setup_lifecycle_service

    candidate = build_candidate_setup()
    return setup_lifecycle_service.process(candidate, market_data_service.latest_candle())


def save_setup(db: Session, setup: TradeSetup) -> TradeSetupRecord:
    record = TradeSetupRecord(
        symbol=setup.symbol,
        direction=setup.direction,
        confidence=setup.confidence,
        entry=setup.entry or 0,
        stop_loss=setup.stop_loss or 0,
        take_profit_1=setup.take_profit_1 or 0,
        take_profit_2=setup.take_profit_2 or 0,
        risk_reward=setup.risk_reward or 0,
        status=setup.status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
