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
    # Three-way spatial cluster BONUS: OTE + supply/demand + supportive GEX
    # level in the same price area. Sub-scored in setup_service:
    #   OTE overlaps S/D zone (+5), relevant GEX level inside that area (+5),
    #   gamma flip near entry (+3), zone+GEX agree with direction (+2).
    # Weights now sum to 115; the final score is capped at 100, so the
    # cluster acts as a bonus that lifts spatially-aligned setups.
    "level_cluster": 15,
}


def calculate_confidence(flags: dict[str, bool | float]) -> tuple[float, dict[str, float]]:
    """Return a transparent confluence score and awarded points by component.

    Boolean flags receive either all or none of a component's weight. Numeric
    flags are interpreted as a normalized 0..1 quality value and receive a
    proportional score. Total is capped at 100 (level_cluster is a bonus).
    """
    components: dict[str, float] = {}

    for name, weight in DEFAULT_WEIGHTS.items():
        value = flags.get(name, False)
        if isinstance(value, bool):
            awarded = float(weight if value else 0)
        else:
            awarded = max(0.0, min(float(weight), float(value) * weight))
        components[name] = round(awarded, 1)

    return round(min(100.0, sum(components.values())), 1), components
