from dataclasses import dataclass
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
) -> dict[float, dict[str, float]]:
    result: dict[float, dict[str, float]] = {}
    for position in positions:
        strike = float(position.strike)
        bucket = result.setdefault(strike, {"call": 0.0, "put": 0.0, "net": 0.0})
        value = calculate_position_gex(futures_price, position)
        if position.option_type.upper() == "CALL":
            bucket["call"] += value
        else:
            bucket["put"] += value
        bucket["net"] += value
    return dict(sorted(result.items()))


def aggregate_gex_by_strike(
    futures_price: float,
    positions: list[OptionPosition],
) -> dict[float, float]:
    components = aggregate_gex_components_by_strike(futures_price, positions)
    return {strike: values["net"] for strike, values in components.items()}


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


def _strength(value: float, total_abs: float) -> int:
    return min(5, max(1, round(abs(value) / max(total_abs / 5, 1e-9))))


def derive_gex_summary_from_positions(
    futures_price: float,
    positions: list[OptionPosition],
    flip_range_points: float | None = None,
    flip_step: float = 5.0,
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
            "levels": [],
            "by_strike": [],
        }

    components = aggregate_gex_components_by_strike(futures_price, positions)
    net_gex = sum(values["net"] for values in components.values())
    regime = "POSITIVE" if net_gex > 0 else "NEGATIVE" if net_gex < 0 else "NEUTRAL"

    call_wall = max(components, key=lambda strike: components[strike]["call"])
    put_wall = min(components, key=lambda strike: components[strike]["put"])
    call_wall_gex = components[call_wall]["call"]
    put_wall_gex = components[put_wall]["put"]
    gamma_flip = calculate_gamma_flip(
        futures_price,
        positions,
        range_points=flip_range_points,
        step=max(float(flip_step), 0.01),
    )

    total_abs = sum(abs(values["net"]) for values in components.values()) or 1.0
    ranked = sorted(
        ((strike, values["net"]) for strike, values in components.items()),
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
        "levels": levels,
        "by_strike": by_strike,
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
            "levels": [],
            "by_strike": [],
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
        "levels": levels,
        "by_strike": by_strike,
    }
