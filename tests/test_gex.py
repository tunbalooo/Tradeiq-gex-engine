from engine.gex import OptionPosition, aggregate_gex_by_strike, black76_gamma


def test_black76_gamma_is_positive():
    gamma = black76_gamma(
        futures_price=25000,
        strike=25000,
        expiry_years=7 / 365,
        implied_volatility=0.20,
    )
    assert gamma > 0


def test_aggregate_gex_by_strike():
    positions = [
        OptionPosition(25000, 7 / 365, "CALL", 1000, 0.20),
        OptionPosition(25000, 7 / 365, "PUT", 500, 0.20),
    ]
    result = aggregate_gex_by_strike(25000, positions)
    assert 25000 in result
    assert result[25000] > 0
