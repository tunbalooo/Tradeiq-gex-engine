from backend.models.schemas import GexLevel, GexSummary, Zone
from engine.confluence_cluster import ClusterResult
from engine.risk_engine import build_trade_levels


def test_targets_use_market_levels_then_fallback():
    zone = Zone(timeframe="15m", kind="DEMAND", low=100, high=102, strength=5)
    cluster = ClusterResult(0.9, 100.5, 102, zone, 101, "Strong +GEX", True, True)
    gex = GexSummary(
        regime="POSITIVE", gamma_flip=99, put_wall=95, call_wall=112,
        net_gex=1, levels=[GexLevel(type="Strong +GEX", price=108, gex=1, strength=4)],
    )
    result = build_trade_levels(
        direction="LONG", current_price=106, ote_low=100.5, ote_high=103,
        ideal_ote=101.5, zones=[zone], atr=4, cluster=cluster, gex=gex,
        previous_liquidity_high=108, previous_liquidity_low=98,
        session_high=110, session_low=96, sweep_price=99.5,
    )
    assert result["entry_valid"] is True
    assert result["take_profit_1"] > result["entry"]
    assert result["tp2_r"] >= 2
    assert result["target_sources"]["tp1"] != ""
