from dataclasses import dataclass


@dataclass(slots=True)
class FibPoint:
    ratio: float
    price: float
    label: str


def calculate_fib_levels(
    swing_low: float,
    swing_high: float,
    direction: str,
) -> list[FibPoint]:
    if swing_high <= swing_low:
        raise ValueError("swing_high must be greater than swing_low")

    ratios = [
        (0.236, "23.6%"),
        (0.382, "38.2%"),
        (0.500, "50.0%"),
        (0.618, "OTE start"),
        (0.705, "Ideal OTE"),
        (0.786, "OTE end"),
    ]
    span = swing_high - swing_low

    points: list[FibPoint] = []
    for ratio, label in ratios:
        if direction.upper() == "LONG":
            price = swing_high - span * ratio
        elif direction.upper() == "SHORT":
            price = swing_low + span * ratio
        else:
            raise ValueError("direction must be LONG or SHORT")
        points.append(FibPoint(ratio=ratio, price=round(price, 2), label=label))
    return points


def ote_zone(
    swing_low: float,
    swing_high: float,
    direction: str,
) -> tuple[float, float]:
    levels = calculate_fib_levels(swing_low, swing_high, direction)
    selected = [p.price for p in levels if p.ratio in {0.618, 0.705, 0.786}]
    return min(selected), max(selected)
