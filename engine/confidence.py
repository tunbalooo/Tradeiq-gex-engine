DEFAULT_WEIGHTS = {
    "trend_alignment": 15,
    "gex_alignment": 15,
    "liquidity_sweep": 15,
    "displacement": 10,
    "ote_overlap": 10,
    "supply_demand": 10,
    "std_dev_confluence": 5,
    "vwap_alignment": 5,
    "session_volatility": 5,
    "risk_reward": 10,
}


def calculate_confidence(flags: dict[str, bool | float]) -> tuple[float, dict[str, float]]:
    """Return a transparent confluence score and awarded points by component.

    Boolean flags receive either all or none of a component's weight. Numeric
    flags are interpreted as a normalized 0..1 quality value and receive a
    proportional score.
    """
    components: dict[str, float] = {}

    for name, weight in DEFAULT_WEIGHTS.items():
        value = flags.get(name, False)
        if isinstance(value, bool):
            awarded = float(weight if value else 0)
        else:
            awarded = max(0.0, min(float(weight), float(value) * weight))
        components[name] = round(awarded, 1)

    return round(sum(components.values()), 1), components
