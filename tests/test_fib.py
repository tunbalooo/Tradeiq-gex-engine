from engine.fib_ote import calculate_fib_levels, ote_zone


def test_long_fib_retraces_from_high():
    levels = calculate_fib_levels(100, 200, "LONG")
    ideal = next(level for level in levels if level.ratio == 0.705)
    assert ideal.price == 129.5


def test_ote_zone_is_ordered():
    low, high = ote_zone(100, 200, "SHORT")
    assert low < high
