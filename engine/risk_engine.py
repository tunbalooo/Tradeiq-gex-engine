from backend.models.schemas import Zone


def build_trade_levels(
    direction: str,
    current_price: float,
    ote_low: float,
    ote_high: float,
    zones: list[Zone],
    atr: float,
    reward_multiple_1: float = 2.0,
    reward_multiple_2: float = 3.5,
) -> dict:
    direction = direction.upper()

    if direction == "LONG":
        demand = [z for z in zones if z.kind == "DEMAND" and z.low <= ote_high and z.high >= ote_low]
        selected = max(demand, key=lambda z: z.strength, default=None)
        entry = selected.high if selected else (ote_low + ote_high) / 2
        stop = (selected.low if selected else ote_low) - atr * 0.25
        risk = max(entry - stop, 0.25)
        tp1 = entry + risk * reward_multiple_1
        tp2 = entry + risk * reward_multiple_2

    elif direction == "SHORT":
        supply = [z for z in zones if z.kind == "SUPPLY" and z.low <= ote_high and z.high >= ote_low]
        selected = max(supply, key=lambda z: z.strength, default=None)
        entry = selected.low if selected else (ote_low + ote_high) / 2
        stop = (selected.high if selected else ote_high) + atr * 0.25
        risk = max(stop - entry, 0.25)
        tp1 = entry - risk * reward_multiple_1
        tp2 = entry - risk * reward_multiple_2

    else:
        return {
            "entry": None,
            "stop_loss": None,
            "take_profit_1": None,
            "take_profit_2": None,
            "risk_reward": None,
        }

    return {
        "entry": round(entry * 4) / 4,
        "stop_loss": round(stop * 4) / 4,
        "take_profit_1": round(tp1 * 4) / 4,
        "take_profit_2": round(tp2 * 4) / 4,
        "risk_reward": reward_multiple_2,
    }
