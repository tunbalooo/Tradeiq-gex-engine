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


def calculate_position_gex(
    futures_price: float,
    position: OptionPosition,
    contract_multiplier: int = 20,
) -> float:
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
        * position.open_interest
        * contract_multiplier
        * futures_price**2
        * 0.01
    )


def aggregate_gex_by_strike(
    futures_price: float,
    positions: list[OptionPosition],
) -> dict[float, float]:
    result: dict[float, float] = {}
    for position in positions:
        result[position.strike] = result.get(position.strike, 0.0) + calculate_position_gex(
            futures_price, position
        )
    return dict(sorted(result.items()))


def derive_gex_summary(
    futures_price: float,
    strike_gex: dict[float, float],
) -> dict:
    if not strike_gex:
        return {
            "regime": "NEUTRAL",
            "gamma_flip": futures_price,
            "put_wall": futures_price,
            "call_wall": futures_price,
            "net_gex": 0.0,
            "levels": [],
        }

    net_gex = sum(strike_gex.values())
    regime = "POSITIVE" if net_gex > 0 else "NEGATIVE" if net_gex < 0 else "NEUTRAL"

    call_wall = max(strike_gex, key=lambda k: strike_gex[k])
    put_wall = min(strike_gex, key=lambda k: strike_gex[k])

    sorted_strikes = sorted(strike_gex)
    cumulative = 0.0
    flip = min(sorted_strikes, key=lambda strike: abs(strike - futures_price))
    total_abs = sum(abs(v) for v in strike_gex.values()) or 1.0

    for strike in sorted_strikes:
        cumulative += strike_gex[strike]
        if abs(cumulative) <= total_abs * 0.08:
            flip = strike

    ranked = sorted(strike_gex.items(), key=lambda item: abs(item[1]), reverse=True)[:8]
    levels = []
    for strike, value in ranked:
        levels.append(
            {
                "type": "Strong +GEX" if value >= 0 else "Strong -GEX",
                "price": strike,
                "gex": value,
                "strength": min(5, max(1, round(abs(value) / (total_abs / 5)))),
            }
        )

    return {
        "regime": regime,
        "gamma_flip": float(flip),
        "put_wall": float(put_wall),
        "call_wall": float(call_wall),
        "net_gex": float(net_gex),
        "levels": levels,
    }
