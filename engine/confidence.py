DEFAULT_WEIGHTS = {
    "trend_alignment": 15,
    "gex_alignment": 15,
    "liquidity_sweep": 10,
    "displacement": 10,
    "ote_overlap": 10,
    "supply_demand": 10,
    "gex_ote_zone_cluster": 15,
    "std_dev_confluence": 5,
    "vwap_alignment": 5,
    "session_volatility": 3,
    "risk_reward": 2,
}


def calculate_confidence(flags: dict[str, bool | float]) -> tuple[float, dict[str, float]]:
    components: dict[str, float] = {}
    for name, weight in DEFAULT_WEIGHTS.items():
        value = flags.get(name, False)
        if isinstance(value, bool):
            awarded = float(weight if value else 0)
        else:
            awarded = max(0.0, min(float(weight), float(value) * weight))
        components[name] = round(awarded, 1)
    return round(sum(components.values()), 1), components
