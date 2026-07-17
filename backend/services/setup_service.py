from datetime import datetime, timedelta, timezone
from math import exp

from sqlalchemy.orm import Session

from backend.models.db_models import TradeSetupRecord
from backend.models.schemas import GexSummary, TradeSetup
from backend.services.market_data import market_data_service
from backend.services.timeframes import aggregate_candles
from engine.confidence import DEFAULT_WEIGHTS, calculate_confidence
from engine.fib_ote import calculate_fib_levels, ote_zone
from engine.gex import OptionPosition, aggregate_gex_by_strike, derive_gex_summary
from engine.market_structure import analyze_market_structure
from engine.risk_engine import build_trade_levels
from engine.supply_demand import detect_supply_demand


def average_true_range(candles, period: int = 14) -> float:
    if len(candles) < period + 1:
        return 12.0

    true_ranges = []
    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(true_ranges[-period:]) / period


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
    """Stable synthetic NQ option chain for development without paid data."""
    positions: list[OptionPosition] = []
    center = round(price / 25) * 25

    for strike in range(int(center - 300), int(center + 325), 25):
        distance = abs(strike - center)
        decay = exp(-distance / 155)
        base_oi = int(650 + 5100 * decay)
        expiry = 7 / 365
        iv = 0.185 + distance / max(price, 1) * 2.25

        call_boost = 1.0
        put_boost = 1.0
        if strike == center + 75:
            call_boost = 2.85
        elif strike == center + 50:
            call_boost = 1.75
        if strike == center - 100:
            put_boost = 3.0
        elif strike == center - 75:
            put_boost = 1.85

        # A deterministic skew keeps the prototype stable between updates.
        call_oi = int(base_oi * call_boost * (1.02 + ((strike // 25) % 5) * 0.025))
        put_oi = int(base_oi * put_boost * (0.98 + ((strike // 25) % 4) * 0.03))

        positions.append(
            OptionPosition(
                strike=strike,
                expiry_years=expiry,
                option_type="CALL",
                open_interest=call_oi,
                implied_volatility=iv,
            )
        )
        positions.append(
            OptionPosition(
                strike=strike,
                expiry_years=expiry,
                option_type="PUT",
                open_interest=put_oi,
                implied_volatility=iv * 1.035,
            )
        )

    return positions


def proximity_score(price: float, low: float, high: float, tolerance: float) -> float:
    if low <= price <= high:
        return 1.0
    distance = min(abs(price - low), abs(price - high))
    return max(0.0, 1.0 - distance / max(tolerance, 0.25))


def build_current_setup() -> TradeSetup:
    base_candles = market_data_service.snapshot()
    candles_5m = aggregate_candles(base_candles, 5)
    candles_15m = aggregate_candles(base_candles, 15)
    candles_60m = aggregate_candles(base_candles, 60)
    current_price = base_candles[-1].close

    structure = analyze_market_structure(candles_5m)
    zones = (
        detect_supply_demand(candles_5m, timeframe="5m", lookback=70)
        + detect_supply_demand(candles_15m, timeframe="15m", lookback=48)
        + detect_supply_demand(candles_60m, timeframe="1H", lookback=24)
    )
    zones = sorted(zones, key=lambda zone: (zone.strength, zone.timeframe), reverse=True)[:10]

    positions = mock_option_chain(current_price)
    strike_gex = aggregate_gex_by_strike(current_price, positions)
    gex_raw = derive_gex_summary(current_price, strike_gex)
    gex = GexSummary(**gex_raw)

    direction = (
        "LONG"
        if structure["trend"] == "BULLISH"
        else "SHORT"
        if structure["trend"] == "BEARISH"
        else "LONG"
        if current_price >= gex.gamma_flip
        else "SHORT"
    )

    swing_low = structure["swing_low"]
    swing_high = structure["swing_high"]
    if swing_high <= swing_low:
        swing_high = swing_low + 20

    fib_points = calculate_fib_levels(swing_low, swing_high, direction)
    fib_levels = [
        {"ratio": point.ratio, "price": point.price, "label": point.label}
        for point in fib_points
    ]
    ote_low, ote_high = ote_zone(swing_low, swing_high, direction)

    atr = average_true_range(candles_5m)
    levels = build_trade_levels(
        direction=direction,
        current_price=current_price,
        ote_low=ote_low,
        ote_high=ote_high,
        zones=zones,
        atr=atr,
    )

    session_candles = base_candles[-390:]
    vwap = calculate_vwap(session_candles)
    std_low, std_high = standard_deviation_levels(session_candles, vwap)

    matching_zones = [
        zone
        for zone in zones
        if ((direction == "LONG" and zone.kind == "DEMAND") or (direction == "SHORT" and zone.kind == "SUPPLY"))
    ]
    zone_quality = 0.0
    for zone in matching_zones:
        overlap = not (zone.high < ote_low or zone.low > ote_high)
        if overlap:
            zone_quality = max(zone_quality, zone.strength / 5)
        else:
            zone_quality = max(
                zone_quality,
                proximity_score(current_price, zone.low, zone.high, atr * 3) * zone.strength / 5,
            )

    gex_alignment = (direction == "LONG" and current_price >= gex.gamma_flip) or (
        direction == "SHORT" and current_price <= gex.gamma_flip
    )
    vwap_alignment = (direction == "LONG" and current_price >= vwap) or (
        direction == "SHORT" and current_price <= vwap
    )
    std_score = max(
        proximity_score(current_price, std_low - atr * 0.25, std_low + atr * 0.25, atr * 2),
        proximity_score(current_price, std_high - atr * 0.25, std_high + atr * 0.25, atr * 2),
    )
    ote_score = proximity_score(current_price, ote_low, ote_high, atr * 3.5)

    ranges = [c.high - c.low for c in candles_5m[-30:]]
    normal_range = sum(ranges) / len(ranges) if ranges else atr
    volatility_quality = max(0.2, min(1.0, normal_range / max(atr, 0.25)))

    flags = {
        "trend_alignment": structure["ema_aligned"],
        "gex_alignment": gex_alignment,
        "liquidity_sweep": structure["liquidity_sweep"],
        "displacement": structure["displacement"],
        "ote_overlap": ote_score,
        "supply_demand": zone_quality,
        "std_dev_confluence": std_score,
        "vwap_alignment": vwap_alignment,
        "session_volatility": volatility_quality,
        "risk_reward": 1.0 if (levels["risk_reward"] or 0) >= 2 else 0.0,
    }
    confidence, components = calculate_confidence(flags)

    nearest_target_wall = gex.call_wall if direction == "LONG" else gex.put_wall
    approaching_wall = abs(nearest_target_wall - current_price) <= atr * 5
    signals = {
        "trend_alignment": bool(structure["ema_aligned"]),
        "gex_alignment": gex_alignment,
        "liquidity_sweep": bool(structure["liquidity_sweep"]),
        "displacement": bool(structure["displacement"]),
        "ote_overlap": ote_score >= 0.72,
        "supply_demand": zone_quality >= 0.65,
        "std_dev_confluence": std_score >= 0.7,
        "vwap_alignment": vwap_alignment,
        "approaching_wall": approaching_wall,
    }

    rationale: list[str] = []
    if structure["ema_aligned"]:
        rationale.append("The 9/21/55 EMA structure is aligned with the setup direction.")
    if gex_alignment:
        rationale.append("Price is on the supportive side of the current gamma flip.")
    if structure["liquidity_sweep"]:
        rationale.append("A recent liquidity sweep was detected before the proposed entry.")
    if structure["displacement"]:
        rationale.append("Recent price action contains a displacement candle.")
    if ote_score >= 0.72:
        rationale.append("Price is inside or close to the active 0.618–0.786 OTE zone.")
    if zone_quality >= 0.65:
        rationale.append("The OTE area overlaps or approaches a strong supply/demand zone.")
    if vwap_alignment:
        rationale.append("Price is aligned with session VWAP.")
    if std_score >= 0.7:
        rationale.append("A session standard-deviation level supports the setup area.")
    if not rationale:
        rationale.append("The system is scanning; the setup does not yet have enough independent confluence.")

    if confidence >= 75:
        status = "WAITING_FOR_LIMIT"
    elif confidence >= 55:
        status = "DEVELOPING"
    else:
        status = "SCANNING"

    now = datetime.now(timezone.utc)
    return TradeSetup(
        timestamp=now,
        valid_until=now + timedelta(minutes=30),
        direction=direction,
        confidence=confidence,
        confidence_components=components,
        confidence_maximums={name: float(weight) for name, weight in DEFAULT_WEIGHTS.items()},
        signals=signals,
        entry=levels["entry"],
        stop_loss=levels["stop_loss"],
        take_profit_1=levels["take_profit_1"],
        take_profit_2=levels["take_profit_2"],
        risk_reward=levels["risk_reward"],
        status=status,
        rationale=rationale,
        gex=gex,
        zones=zones,
        fib_levels=fib_levels,
        atr=round(atr, 2),
        vwap=round(vwap, 2),
        standard_deviation_high=round(std_high, 2),
        standard_deviation_low=round(std_low, 2),
    )


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
