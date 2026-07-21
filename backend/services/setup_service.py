from datetime import datetime, timedelta, timezone
from math import exp
import threading
from uuid import uuid4

from backend.core.config import settings
from backend.models.schemas import GexSummary, TradeSetup
from backend.services.databento_gex import gex_service
from backend.services.decision_brain import decision_brain_service
from backend.services.market_data import market_data_service, rth_candles
from backend.services.instruments import InstrumentProfile, instrument_registry
from backend.services.timeframes import aggregate_candles
from engine.confidence import DEFAULT_WEIGHTS, calculate_confidence
from engine.confluence_cluster import find_confluence_cluster
from engine.fib_ote import calculate_fib_levels, ote_zone
from engine.fib_pullback_continuation import analyze_fib_pullback_continuation
from engine.gex import OptionPosition, derive_gex_summary_from_positions
from engine.market_structure import analyze_market_structure
from engine.entry_models import ModelContext, rank_entry_models
from engine.institutional_confidence import CATEGORY_WEIGHTS, calculate_institutional_confidence
from engine.risk_engine import build_trade_levels
from engine.supply_demand import detect_supply_demand


_FALLBACK_GEX_LOCK = threading.RLock()
_FALLBACK_GEX_CACHE: dict[str, tuple[datetime, GexSummary]] = {}


def clear_fallback_gex_cache(symbol: str | None = None) -> None:
    with _FALLBACK_GEX_LOCK:
        if symbol is None:
            _FALLBACK_GEX_CACHE.clear()
        else:
            _FALLBACK_GEX_CACHE.pop(symbol.upper(), None)


def _stable_fallback_gex(current_price: float, profile: InstrumentProfile) -> GexSummary:
    """Build a fallback GEX map once per refresh window instead of every tick."""
    now = datetime.now(timezone.utc)
    with _FALLBACK_GEX_LOCK:
        cached = _FALLBACK_GEX_CACHE.get(profile.symbol)
        if cached and (now - cached[0]).total_seconds() < max(60, settings.gex_refresh_seconds):
            return cached[1].model_copy(deep=True)

    positions = mock_option_chain(current_price, profile)
    raw = derive_gex_summary_from_positions(
        current_price,
        positions,
        flip_range_points=profile.gex_strike_range_points,
        flip_step=profile.gex_flip_step,
    )
    raw.update({
        "source": "simulated-fallback",
        "updated_at": now,
        "contract_count": len(positions),
        "expiry_count": 1,
        "is_estimate": True,
        "source_symbol": profile.gex_source_symbol,
        "applied_to_symbol": profile.symbol,
        "options_parent": profile.options_parent,
        "source_label": f"Fallback {profile.gex_source_label}",
        "is_parent_market": profile.uses_parent_gex,
    })
    summary = GexSummary(**raw)
    with _FALLBACK_GEX_LOCK:
        _FALLBACK_GEX_CACHE[profile.symbol] = (now, summary)
    return summary.model_copy(deep=True)


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


def mock_option_chain(price: float, profile: InstrumentProfile | None = None) -> list[OptionPosition]:
    instrument = profile or instrument_registry.active
    positions: list[OptionPosition] = []
    increment = instrument.option_strike_increment
    center = round(price / increment) * increment
    count = int((instrument.mock_option_width * 2) / increment)
    for index in range(count + 1):
        strike = center - instrument.mock_option_width + index * increment
        distance = abs(strike - center)
        decay = max(instrument.mock_option_width * 0.52, increment)
        base_oi = int(650 + 5100 * exp(-distance / decay))
        iv = instrument.default_iv + distance / max(price, 1) * 2.25
        call_boost = 2.85 if abs(strike - (center + increment * 3)) < increment / 10 else 1.75 if abs(strike - (center + increment * 2)) < increment / 10 else 1.0
        put_boost = 3.0 if abs(strike - (center - increment * 4)) < increment / 10 else 1.85 if abs(strike - (center - increment * 3)) < increment / 10 else 1.0
        positions.extend([
            OptionPosition(strike, 7 / 365, "CALL", int(base_oi * call_boost), iv, contract_multiplier=instrument.gex_contract_multiplier),
            OptionPosition(strike, 7 / 365, "PUT", int(base_oi * put_boost), iv * 1.035, contract_multiplier=instrument.gex_contract_multiplier),
        ])
    return positions

def proximity_score(price: float, low: float, high: float, tolerance: float) -> float:
    if low <= price <= high:
        return 1.0
    return max(0.0, 1.0 - min(abs(price - low), abs(price - high)) / max(tolerance, .25))


def _enrich_gex(gex: GexSummary, current_price: float) -> GexSummary:
    positive = sum(max(0.0, float(item.net_gex)) for item in gex.by_strike)
    negative = sum(abs(min(0.0, float(item.net_gex))) for item in gex.by_strike)
    total = positive + negative
    positive_pct = round(positive / total * 100, 1) if total else 0.0
    negative_pct = round(negative / total * 100, 1) if total else 0.0
    if gex.regime == "POSITIVE":
        dealer_bias = "SUPPORTIVE / MEAN REVERTING" if current_price >= gex.gamma_flip else "PIVOT TEST"
    elif gex.regime == "NEGATIVE":
        dealer_bias = "VOLATILITY EXPANSION"
    else:
        dealer_bias = "NEUTRAL / TRANSITION"
    nodes = sorted(gex.by_strike, key=lambda item: abs(float(item.net_gex)), reverse=True)[:10]
    return gex.model_copy(update={
        "dealer_bias": dealer_bias,
        "positive_gamma_percent": positive_pct,
        "negative_gamma_percent": negative_pct,
        "top_gamma_nodes": [
            {"strike": item.strike, "net_gex": item.net_gex, "call_gex": item.call_gex, "put_gex": item.put_gex}
            for item in nodes
        ],
        "level_meanings": {
            "Gamma Flip": "Dealer pivot where hedging behaviour and market bias may change.",
            "Call Wall": "Major call-gamma resistance and potential upside pin/rejection area.",
            "Put Wall": "Major put-gamma support and potential downside pin/bounce area.",
            "Max Pain": "Expiration pinning reference; context only, never an entry by itself.",
            "Positive Gamma": "Dealers may dampen volatility and encourage mean reversion.",
            "Negative Gamma": "Dealer hedging may amplify directional volatility.",
        },
    })


def _direction_from_structure(structure: dict, current_price: float, gex: GexSummary) -> str:
    if structure["trend"] == "BULLISH":
        return "LONG"
    if structure["trend"] == "BEARISH":
        return "SHORT"
    return "LONG" if current_price >= gex.gamma_flip else "SHORT"


def build_candidate_setup(candles_override=None, profile_override: InstrumentProfile | None = None, gex_override: GexSummary | None = None) -> TradeSetup:
    profile = profile_override or instrument_registry.active
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

    gex = gex_override
    # Native GEX belongs to the currently selected market. Background radar
    # scans must never change the global instrument merely to obtain GEX, so
    # inactive markets use the stable fallback map until the trader opens them.
    if gex is None and profile.symbol == instrument_registry.active.symbol:
        gex = gex_service.get_summary(current_price)
    if gex is None:
        gex = _stable_fallback_gex(current_price, profile)

    gex = _enrich_gex(gex, current_price)
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
    session = rth_candles(base_candles, profile=profile)
    session_high, session_low = max(c.high for c in session), min(c.low for c in session)
    vwap = calculate_vwap(session)
    std_low, std_high = standard_deviation_levels(session, vwap)
    previous_volumes = [float(c.volume) for c in candles_5m[-21:-1]]
    average_volume = sum(previous_volumes) / len(previous_volumes) if previous_volumes else max(float(candles_5m[-1].volume), 1.0)
    volume_ratio = float(candles_5m[-1].volume) / max(average_volume, 1.0)
    volume_expansion_quality = max(0.0, min(1.0, (volume_ratio - 0.65) / 0.85))
    session_quality = max(0.0, min(1.0, len(session) / 36.0))

    direction_sweep = structure["sell_side_sweep"] if direction == "LONG" else structure["buy_side_sweep"]
    direction_displacement = structure["bullish_displacement"] if direction == "LONG" else structure["bearish_displacement"]
    direction_fvg = structure["bullish_fvg"] if direction == "LONG" else structure["bearish_fvg"]
    ordered_sequence = structure["bullish_sequence"] if direction == "LONG" else structure["bearish_sequence"]
    trend_alignment = structure["bullish_ema_aligned"] if direction == "LONG" else structure["bearish_ema_aligned"]
    fib_pullback = analyze_fib_pullback_continuation(
        base_candles, direction=direction, swing_low=swing_low, swing_high=swing_high,
        current_price=current_price, atr=atr, tick_size=profile.tick_size,
    )

    levels = build_trade_levels(
        direction=direction, current_price=current_price, ote_low=ote_low, ote_high=ote_high,
        ideal_ote=ideal_ote, zones=zones, atr=atr, cluster=cluster, gex=gex,
        previous_liquidity_high=structure["previous_liquidity_high"],
        previous_liquidity_low=structure["previous_liquidity_low"],
        session_high=session_high, session_low=session_low,
        sweep_price=structure["sweep_price"] if direction_sweep else None,
        tick_size=profile.tick_size,
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
    legacy_confidence, components = calculate_confidence(flags)
    structure_quality = 1.0 if ordered_sequence else .8 if direction_sweep and direction_displacement else .55 if direction_displacement or direction_fvg else .2 if trend_alignment else 0.0
    gex_quality = max(0.0, min(1.0, (.55 if gex_alignment else 0.0) + cluster.score * .45))
    institutional_evidence = {
        "trend": 1.0 if trend_alignment else .25 if structure["trend"] != "NEUTRAL" else 0.0,
        "structure": structure_quality,
        "gex": gex_quality,
        "liquidity": 1.0 if direction_sweep else .25 if structure["liquidity_sweep"] else 0.0,
        "momentum": max(displacement_quality, volatility_quality * .65),
        "volume": volume_expansion_quality,
        "session": session_quality,
    }
    confidence, institutional_components, confidence_grade = calculate_institutional_confidence(institutional_evidence)
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
        "legacy_confluence_score": legacy_confidence,
        "volume_ratio": round(volume_ratio, 3),
        "volume_expansion": volume_expansion_quality >= .6,
        "directional_fvg_low": structure.get("bullish_fvg_low") if direction == "LONG" else structure.get("bearish_fvg_low"),
        "directional_fvg_high": structure.get("bullish_fvg_high") if direction == "LONG" else structure.get("bearish_fvg_high"),
        "previous_liquidity_low": structure.get("previous_liquidity_low"),
        "previous_liquidity_high": structure.get("previous_liquidity_high"),
        "sweep_price": structure.get("sweep_price"),
        "fib_pullback_zone": True,
        "fib_pullback_zone_low": fib_pullback.zone_low,
        "fib_pullback_zone_high": fib_pullback.zone_high,
        "fib_pullback_watch_price": fib_pullback.watch_price,
        "fib_pullback_invalidation": fib_pullback.invalidation_price,
        "fib_pullback_impulse_quality": fib_pullback.impulse_quality,
        "fib_pullback_touched": fib_pullback.touched,
        "fib_pullback_rejection": fib_pullback.rejection,
        "fib_pullback_confirmed": fib_pullback.confirmed,
        "fib_pullback_confirmation_entry": fib_pullback.confirmation_entry,
        "fib_pullback_entry_fresh": fib_pullback.entry_fresh,
        "fib_pullback_confirmation_candle_time": fib_pullback.confirmation_candle_time.isoformat() if fib_pullback.confirmation_candle_time else None,
    }
    # Rank the institutional entry models before locking a price plan. The top
    # model supplies its own trigger and structural invalidation. This prevents
    # every model from being forced through the old universal OTE/liquidity gate.
    preliminary_context = ModelContext(
        direction=direction, current_price=current_price, atr=atr, proposed_entry=levels["entry"],
        vwap=vwap, gamma_flip=gex.gamma_flip,
        selected_zone_low=selected_zone.low if selected_zone else None,
        selected_zone_high=selected_zone.high if selected_zone else None,
        ote_low=ote_low, ote_high=ote_high,
        fvg_low=signals.get("directional_fvg_low"), fvg_high=signals.get("directional_fvg_high"),
        signals=signals, structure=structure,
        fib_pullback_low=fib_pullback.zone_low, fib_pullback_high=fib_pullback.zone_high,
        fib_pullback_confirmation_entry=fib_pullback.confirmation_entry,
        fib_pullback_invalidation=fib_pullback.invalidation_price,
        volume_expansion=volume_expansion_quality, session_quality=session_quality,
    )
    preliminary_ranking = rank_entry_models(preliminary_context)
    preliminary_primary = next((item for item in preliminary_ranking if item.eligible), preliminary_ranking[0] if preliminary_ranking else None)
    if preliminary_primary and preliminary_primary.trigger_price is not None:
        levels = build_trade_levels(
            direction=direction, current_price=current_price, ote_low=ote_low, ote_high=ote_high,
            ideal_ote=ideal_ote, zones=zones, atr=atr, cluster=cluster, gex=gex,
            previous_liquidity_high=structure["previous_liquidity_high"],
            previous_liquidity_low=structure["previous_liquidity_low"],
            session_high=session_high, session_low=session_low,
            sweep_price=structure["sweep_price"] if direction_sweep else None,
            tick_size=profile.tick_size,
            preferred_entry=preliminary_primary.trigger_price,
            preferred_invalidation=preliminary_primary.invalidation_price,
        )

    signals.update({
        "valid_limit": bool(levels["entry_valid"]),
        "target_not_blocked": not levels["blocked_by_near_target"],
        "selected_model_trigger": preliminary_primary.trigger_price if preliminary_primary else None,
        "selected_model_invalidation": preliminary_primary.invalidation_price if preliminary_primary else None,
    })
    flags["risk_reward"] = 1.0 if levels["entry_valid"] and not levels["blocked_by_near_target"] and (levels["tp2_r"] or 0) >= 2 else 0.0
    legacy_confidence, components = calculate_confidence(flags)

    rationale = []
    if trend_alignment: rationale.append(f"The 9/21/55 EMA structure is {direction.lower()}-aligned.")
    if gex_alignment: rationale.append("Price is on the supportive side of the gamma flip.")
    if ordered_sequence: rationale.append("A recent sweep → displacement → FVG sequence is confirmed in the trade direction.")
    elif direction_sweep or direction_displacement: rationale.append("Directional liquidity/displacement is present, but the full ordered sequence is incomplete.")
    if cluster.score >= settings.cluster_min_score:
        zone_name = f"{cluster.zone.timeframe} {cluster.zone.kind.lower()}" if cluster.zone else "zone"
        rationale.append(f"OTE, {zone_name}, and {cluster.gex_type or 'GEX'} cluster around {cluster.low:,.2f}–{cluster.high:,.2f}.")
    if preliminary_primary:
        rationale.append(f"{preliminary_primary.name} is the current primary entry model at {preliminary_primary.score:.1f}%.")
    if preliminary_primary and preliminary_primary.key == "FIB_PULLBACK_CONTINUATION":
        rationale.append(
            f"The 50%–61.8% continuation zone is {fib_pullback.zone_low:,.2f}–{fib_pullback.zone_high:,.2f}; "
            + ("a closed rejection has confirmed a body-midpoint limit." if fib_pullback.confirmed else "it remains a watch location until a closed rejection confirms execution.")
        )
    if levels["blocked_by_near_target"]: rationale.append("A nearby market level blocks sufficient reward; preview only.")
    if not levels["entry_valid"]: rationale.append("The selected model trigger is not a valid resting limit relative to current price.")
    if levels["target_sources"]: rationale.append(f"TP1 uses {levels['target_sources']['tp1']}; TP2 uses {levels['target_sources']['tp2']}.")
    if not rationale: rationale.append("The engine is scanning for a stronger multi-factor setup.")

    status = "DEVELOPING" if preliminary_primary and preliminary_primary.eligible and preliminary_primary.score >= settings.setup_watch_model_score and levels["entry_valid"] else "SCANNING"
    now = datetime.now(timezone.utc)
    setup = TradeSetup(
        setup_id=f"preview-{uuid4()}", symbol=profile.symbol, timestamp=now,
        valid_until=now + timedelta(minutes=settings.setup_expiry_minutes), direction=direction,
        confidence=confidence, confidence_components=components,
        confidence_maximums={k: float(v) for k, v in DEFAULT_WEIGHTS.items()}, signals=signals,
        confidence_grade=confidence_grade,
        institutional_confidence_components=institutional_components,
        institutional_confidence_maximums={k: float(v) for k, v in CATEGORY_WEIGHTS.items()},
        actionable=False, entry_valid=bool(levels["entry_valid"]),
        order_state="PREVIEW_ONLY",
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
    model_context = ModelContext(
        direction=direction, current_price=current_price, atr=atr, proposed_entry=levels["entry"],
        vwap=vwap, gamma_flip=gex.gamma_flip,
        selected_zone_low=selected_zone.low if selected_zone else None,
        selected_zone_high=selected_zone.high if selected_zone else None,
        ote_low=ote_low, ote_high=ote_high,
        fvg_low=signals.get("directional_fvg_low"), fvg_high=signals.get("directional_fvg_high"),
        signals=signals, structure=structure,
        fib_pullback_low=fib_pullback.zone_low, fib_pullback_high=fib_pullback.zone_high,
        fib_pullback_confirmation_entry=fib_pullback.confirmation_entry,
        fib_pullback_invalidation=fib_pullback.invalidation_price,
        volume_expansion=volume_expansion_quality, session_quality=session_quality,
    )
    return decision_brain_service.select(setup, rank_entry_models(model_context))


def build_current_setup() -> TradeSetup:
    from backend.services.trade_engine import trade_engine_service
    current = trade_engine_service.current_setup()
    return current or build_candidate_setup()
