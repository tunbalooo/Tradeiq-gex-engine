from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, log, sqrt
from statistics import NormalDist


@dataclass(slots=True)
class OptionPosition:
    strike: float
    expiry_years: float
    option_type: str
    open_interest: int
    implied_volatility: float
    rate: float = 0.045
    contract_multiplier: int = 20
    symbol: str | None = None
    expiration_ns: int | None = None
    iv_is_estimated: bool = False


def black76_gamma(
    futures_price: float,
    strike: float,
    expiry_years: float,
    implied_volatility: float,
    rate: float = 0.045,
) -> float:
    if futures_price <= 0 or strike <= 0 or expiry_years <= 0 or implied_volatility <= 0:
        return 0.0

    d1 = (
        log(futures_price / strike)
        + 0.5 * implied_volatility**2 * expiry_years
    ) / (implied_volatility * sqrt(expiry_years))

    normal_pdf = NormalDist().pdf(d1)
    return exp(-rate * expiry_years) * normal_pdf / (
        futures_price * implied_volatility * sqrt(expiry_years)
    )


def calculate_position_gex(futures_price: float, position: OptionPosition) -> float:
    gamma = black76_gamma(
        futures_price=futures_price,
        strike=position.strike,
        expiry_years=position.expiry_years,
        implied_volatility=position.implied_volatility,
        rate=position.rate,
    )
    sign = 1.0 if position.option_type.upper() == "CALL" else -1.0
    return (
        sign
        * gamma
        * max(position.open_interest, 0)
        * max(position.contract_multiplier, 1)
        * futures_price**2
        * 0.01
    )


def aggregate_gex_components_by_strike(
    futures_price: float,
    positions: list[OptionPosition],
) -> dict[float, dict[str, float | int | set[int]]]:
    result: dict[float, dict[str, float | int | set[int]]] = {}
    for position in positions:
        strike = float(position.strike)
        bucket = result.setdefault(
            strike,
            {
                "call": 0.0,
                "put": 0.0,
                "net": 0.0,
                "call_oi": 0,
                "put_oi": 0,
                "iv_oi_sum": 0.0,
                "iv_weight": 0,
                "expirations": set(),
            },
        )
        value = calculate_position_gex(futures_price, position)
        if position.option_type.upper() == "CALL":
            bucket["call"] = float(bucket["call"]) + value
            bucket["call_oi"] = int(bucket["call_oi"]) + max(position.open_interest, 0)
        else:
            bucket["put"] = float(bucket["put"]) + value
            bucket["put_oi"] = int(bucket["put_oi"]) + max(position.open_interest, 0)
        bucket["net"] = float(bucket["net"]) + value
        oi = max(position.open_interest, 0)
        bucket["iv_oi_sum"] = float(bucket["iv_oi_sum"]) + max(position.implied_volatility, 0.0) * oi
        bucket["iv_weight"] = int(bucket["iv_weight"]) + oi
        if position.expiration_ns is not None:
            expirations = bucket["expirations"]
            if isinstance(expirations, set):
                expirations.add(int(position.expiration_ns))
    return dict(sorted(result.items()))


def aggregate_gex_by_strike(
    futures_price: float,
    positions: list[OptionPosition],
) -> dict[float, float]:
    components = aggregate_gex_components_by_strike(futures_price, positions)
    return {strike: float(values["net"]) for strike, values in components.items()}


def net_gex_at_spot(spot: float, positions: list[OptionPosition]) -> float:
    return sum(calculate_position_gex(spot, position) for position in positions)


def calculate_gamma_flip(
    futures_price: float,
    positions: list[OptionPosition],
    range_points: float | None = None,
    step: float = 5.0,
) -> float:
    """Reprice the whole option book across hypothetical futures prices and estimate zero gamma.

    This is materially better than using cumulative exposure by strike because the
    option gamma itself changes as the underlying price changes.
    """
    if not positions:
        return futures_price

    width = range_points or max(300.0, futures_price * 0.035)
    lower = max(step, futures_price - width)
    upper = futures_price + width
    count = max(2, int((upper - lower) / step) + 1)
    spots = [lower + index * step for index in range(count)]
    values = [net_gex_at_spot(spot, positions) for spot in spots]

    crossings: list[float] = []
    for index in range(1, len(spots)):
        left_value, right_value = values[index - 1], values[index]
        if left_value == 0:
            crossings.append(spots[index - 1])
            continue
        if left_value * right_value < 0:
            left_spot, right_spot = spots[index - 1], spots[index]
            fraction = abs(left_value) / (abs(left_value) + abs(right_value))
            crossings.append(left_spot + (right_spot - left_spot) * fraction)

    if crossings:
        return min(crossings, key=lambda value: abs(value - futures_price))
    return spots[min(range(len(spots)), key=lambda index: abs(values[index]))]


def calculate_max_pain(positions: list[OptionPosition]) -> float | None:
    """Estimate options max pain from strike/open-interest payout minimisation."""
    strikes = sorted({float(position.strike) for position in positions if position.open_interest > 0})
    if not strikes:
        return None
    best_strike: float | None = None
    best_payout = float("inf")
    for settlement in strikes:
        payout = 0.0
        for position in positions:
            oi = max(int(position.open_interest), 0)
            if position.option_type.upper() == "CALL":
                intrinsic = max(settlement - position.strike, 0.0)
            else:
                intrinsic = max(position.strike - settlement, 0.0)
            payout += intrinsic * oi * max(position.contract_multiplier, 1)
        if payout < best_payout:
            best_payout = payout
            best_strike = settlement
    return best_strike


def _strength(value: float, total_abs: float) -> int:
    return min(5, max(1, round(abs(value) / max(total_abs / 5, 1e-9))))


def expiry_breakdown(positions: list[OptionPosition], now: datetime | None = None) -> dict[str, int]:
    reference = now or datetime.now(timezone.utc)
    reference_tz = reference.tzinfo or timezone.utc
    today = reference.date()
    buckets = {"0DTE": 0, "WEEKLY": 0, "ALL": len(positions)}
    for position in positions:
        if position.expiration_ns is None:
            continue
        expiration = datetime.fromtimestamp(position.expiration_ns / 1_000_000_000, tz=timezone.utc).astimezone(reference_tz)
        days = (expiration.date() - today).days
        if days == 0:
            buckets["0DTE"] += 1
        if 0 <= days <= 7:
            buckets["WEEKLY"] += 1
    return buckets


def filter_positions_by_expiry(
    positions: list[OptionPosition],
    expiry_filter: str = "ALL",
    now: datetime | None = None,
) -> list[OptionPosition]:
    mode = str(expiry_filter or "ALL").upper()
    if mode == "ALL":
        return list(positions)
    reference = now or datetime.now(timezone.utc)
    reference_tz = reference.tzinfo or timezone.utc
    today = reference.date()
    selected: list[OptionPosition] = []
    for position in positions:
        if position.expiration_ns is None:
            continue
        expiration = datetime.fromtimestamp(position.expiration_ns / 1_000_000_000, tz=timezone.utc).astimezone(reference_tz)
        days = (expiration.date() - today).days
        if mode == "0DTE" and days == 0:
            selected.append(position)
        elif mode == "WEEKLY" and 0 <= days <= 7:
            selected.append(position)
    return selected


def _intensity_zones(
    futures_price: float,
    components: dict[float, dict[str, float | int | set[int]]],
) -> list[dict]:
    if not components:
        return []
    strikes = sorted(components)
    gaps = [right - left for left, right in zip(strikes, strikes[1:]) if right > left]
    increment = sorted(gaps)[len(gaps) // 2] if gaps else max(futures_price * 0.001, 1.0)
    max_abs = max(abs(float(values["net"])) for values in components.values()) or 1.0
    threshold = max_abs * 0.18
    candidates = [strike for strike in strikes if abs(float(components[strike]["net"])) >= threshold]
    groups: list[list[float]] = []
    for strike in candidates:
        sign = 1 if float(components[strike]["net"]) >= 0 else -1
        if not groups:
            groups.append([strike])
            continue
        previous = groups[-1][-1]
        previous_sign = 1 if float(components[previous]["net"]) >= 0 else -1
        if sign == previous_sign and strike - previous <= increment * 1.6:
            groups[-1].append(strike)
        else:
            groups.append([strike])

    zones = []
    for group in groups:
        peak = max(group, key=lambda strike: abs(float(components[strike]["net"])))
        peak_gex = float(components[peak]["net"])
        total_gex = sum(float(components[strike]["net"]) for strike in group)
        positive = peak_gex >= 0
        if positive:
            role = "SUPPORT" if peak <= futures_price else "RESISTANCE"
        else:
            role = "VOLATILITY"
        low = min(group) - increment * 0.35
        high = max(group) + increment * 0.35
        zones.append(
            {
                "low": float(low),
                "high": float(high),
                "midpoint": float((low + high) / 2),
                "sign": "POSITIVE" if positive else "NEGATIVE",
                "role": role,
                "peak_strike": float(peak),
                "peak_gex": peak_gex,
                "total_gex": float(total_gex),
                "strength": min(5, max(1, round(abs(peak_gex) / max_abs * 5))),
                "label": f"{'+GEX' if positive else '-GEX'} {role}",
            }
        )
    return sorted(zones, key=lambda zone: abs(float(zone["peak_gex"])), reverse=True)[:8]


def derive_gex_summary_from_positions(
    futures_price: float,
    positions: list[OptionPosition],
    flip_range_points: float | None = None,
    flip_step: float = 5.0,
    expiry_filter: str = "ALL",
    available_expiry_filters: list[str] | None = None,
    expiry_counts: dict[str, int] | None = None,
) -> dict:
    if not positions:
        return {
            "regime": "NEUTRAL",
            "gamma_flip": futures_price,
            "put_wall": futures_price,
            "call_wall": futures_price,
            "net_gex": 0.0,
            "call_wall_gex": 0.0,
            "put_wall_gex": 0.0,
            "max_pain": None,
            "gamma_resistance": futures_price,
            "gamma_support": futures_price,
            "levels": [],
            "by_strike": [],
            "intensity_zones": [],
            "reference_price": futures_price,
            "expiry_filter": str(expiry_filter).upper(),
            "available_expiry_filters": available_expiry_filters or ["ALL"],
            "expiry_breakdown": expiry_counts or {"ALL": 0},
            "iv_observed_count": 0,
            "iv_estimated_count": 0,
            "calculation_note": "No option positions are available for this expiration view.",
        }

    components = aggregate_gex_components_by_strike(futures_price, positions)
    net_gex = sum(float(values["net"]) for values in components.values())
    regime = "POSITIVE" if net_gex > 0 else "NEGATIVE" if net_gex < 0 else "NEUTRAL"

    call_wall = max(components, key=lambda strike: float(components[strike]["call"]))
    put_wall = min(components, key=lambda strike: float(components[strike]["put"]))
    call_wall_gex = float(components[call_wall]["call"])
    put_wall_gex = float(components[put_wall]["put"])
    gamma_flip = calculate_gamma_flip(
        futures_price,
        positions,
        range_points=flip_range_points,
        step=max(float(flip_step), 0.01),
    )
    max_pain = calculate_max_pain(positions)
    positive_above = [strike for strike, values in components.items() if strike >= futures_price and float(values["net"]) > 0]
    positive_below = [strike for strike, values in components.items() if strike <= futures_price and float(values["net"]) > 0]
    gamma_resistance = max(positive_above, key=lambda strike: float(components[strike]["net"]), default=call_wall)
    gamma_support = max(positive_below, key=lambda strike: float(components[strike]["net"]), default=put_wall)

    total_abs = sum(abs(float(values["net"])) for values in components.values()) or 1.0
    ranked = sorted(
        ((strike, float(values["net"])) for strike, values in components.items()),
        key=lambda item: abs(item[1]),
        reverse=True,
    )[:12]
    levels = [
        {
            "type": "Strong +GEX" if value >= 0 else "Strong -GEX",
            "price": float(strike),
            "gex": float(value),
            "strength": _strength(value, total_abs),
        }
        for strike, value in ranked
    ]
    by_strike = [
        {
            "strike": float(strike),
            "call_gex": float(values["call"]),
            "put_gex": float(values["put"]),
            "net_gex": float(values["net"]),
            "call_oi": int(values["call_oi"]),
            "put_oi": int(values["put_oi"]),
            "total_oi": int(values["call_oi"]) + int(values["put_oi"]),
            "weighted_iv": (
                float(values["iv_oi_sum"]) / int(values["iv_weight"])
                if int(values["iv_weight"]) > 0
                else None
            ),
            "expiration_count": len(values["expirations"]) if isinstance(values["expirations"], set) else 0,
        }
        for strike, values in components.items()
    ]

    return {
        "regime": regime,
        "gamma_flip": float(gamma_flip),
        "put_wall": float(put_wall),
        "call_wall": float(call_wall),
        "net_gex": float(net_gex),
        "call_wall_gex": float(call_wall_gex),
        "put_wall_gex": float(put_wall_gex),
        "max_pain": float(max_pain) if max_pain is not None else None,
        "gamma_resistance": float(gamma_resistance),
        "gamma_support": float(gamma_support),
        "levels": levels,
        "by_strike": by_strike,
        "intensity_zones": _intensity_zones(futures_price, components),
        "reference_price": float(futures_price),
        "expiry_filter": str(expiry_filter).upper(),
        "available_expiry_filters": available_expiry_filters or ["ALL"],
        "expiry_breakdown": expiry_counts or {"ALL": len(positions)},
        "iv_observed_count": sum(1 for position in positions if not position.iv_is_estimated),
        "iv_estimated_count": sum(1 for position in positions if position.iv_is_estimated),
        "calculation_note": (
            "Native open interest with a mix of observed and model-estimated implied volatility."
            if any(position.iv_is_estimated for position in positions)
            else "Native open interest and observed implied volatility were used for all included contracts."
        ),
    }


def derive_gex_summary(futures_price: float, strike_gex: dict[float, float]) -> dict:
    """Backwards-compatible summary when only net strike GEX is available."""
    if not strike_gex:
        return {
            "regime": "NEUTRAL",
            "gamma_flip": futures_price,
            "put_wall": futures_price,
            "call_wall": futures_price,
            "net_gex": 0.0,
            "call_wall_gex": 0.0,
            "put_wall_gex": 0.0,
            "max_pain": None,
            "gamma_resistance": futures_price,
            "gamma_support": futures_price,
            "levels": [],
            "by_strike": [],
            "intensity_zones": [],
            "reference_price": futures_price,
            "expiry_filter": "ALL",
            "available_expiry_filters": ["ALL"],
            "expiry_breakdown": {"ALL": 0},
            "iv_observed_count": 0,
            "iv_estimated_count": 0,
            "calculation_note": "Fallback GEX profile; native option positioning is unavailable.",
        }

    net_gex = sum(strike_gex.values())
    regime = "POSITIVE" if net_gex > 0 else "NEGATIVE" if net_gex < 0 else "NEUTRAL"
    call_wall = max(strike_gex, key=lambda strike: strike_gex[strike])
    put_wall = min(strike_gex, key=lambda strike: strike_gex[strike])

    cumulative = 0.0
    best_flip = min(strike_gex, key=lambda strike: abs(strike - futures_price))
    best_abs = float("inf")
    for strike, value in sorted(strike_gex.items()):
        cumulative += value
        if abs(cumulative) < best_abs:
            best_abs = abs(cumulative)
            best_flip = strike

    total_abs = sum(abs(value) for value in strike_gex.values()) or 1.0
    ranked = sorted(strike_gex.items(), key=lambda item: abs(item[1]), reverse=True)[:10]
    levels = [
        {
            "type": "Strong +GEX" if value >= 0 else "Strong -GEX",
            "price": float(strike),
            "gex": float(value),
            "strength": _strength(value, total_abs),
        }
        for strike, value in ranked
    ]
    by_strike = [
        {
            "strike": float(strike),
            "call_gex": float(max(value, 0.0)),
            "put_gex": float(min(value, 0.0)),
            "net_gex": float(value),
            "call_oi": 0,
            "put_oi": 0,
            "total_oi": 0,
            "weighted_iv": None,
            "expiration_count": 0,
        }
        for strike, value in sorted(strike_gex.items())
    ]
    return {
        "regime": regime,
        "gamma_flip": float(best_flip),
        "put_wall": float(put_wall),
        "call_wall": float(call_wall),
        "net_gex": float(net_gex),
        "call_wall_gex": float(strike_gex[call_wall]),
        "put_wall_gex": float(strike_gex[put_wall]),
        "max_pain": None,
        "gamma_resistance": float(call_wall),
        "gamma_support": float(put_wall),
        "levels": levels,
        "by_strike": by_strike,
        "intensity_zones": [],
        "reference_price": float(futures_price),
        "expiry_filter": "ALL",
        "available_expiry_filters": ["ALL"],
        "expiry_breakdown": {"ALL": len(strike_gex)},
        "iv_observed_count": 0,
        "iv_estimated_count": 0,
        "calculation_note": "Net-strike fallback profile without contract-level open-interest metadata.",
    }
