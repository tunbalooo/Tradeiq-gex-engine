from engine.confidence import calculate_confidence


def test_full_score_is_100():
    score, components = calculate_confidence({
        "trend_alignment": True,
        "gex_alignment": True,
        "liquidity_sweep": True,
        "displacement": True,
        "ote_overlap": True,
        "supply_demand": True,
        "gex_ote_zone_cluster": True,
        "std_dev_confluence": True,
        "vwap_alignment": True,
        "session_volatility": 1.0,
        "risk_reward": 1.0,
    })
    assert score == 100
    assert sum(components.values()) == 100
