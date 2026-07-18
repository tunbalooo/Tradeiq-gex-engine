from backend.models.schemas import GexLevel, GexSummary, Zone
from engine.confluence_cluster import find_confluence_cluster


def test_three_way_cluster_scores_high():
    gex = GexSummary(
        regime="POSITIVE",
        gamma_flip=100.5,
        put_wall=99.5,
        call_wall=110,
        net_gex=1_000_000,
        levels=[GexLevel(type="Strong +GEX", price=101.0, gex=500_000, strength=5)],
    )
    zones = [Zone(timeframe="15m", kind="DEMAND", low=100, high=102, strength=5, fresh=True)]
    cluster = find_confluence_cluster("LONG", 100.5, 102.5, zones, gex, atr=8, current_price=106)
    assert cluster.score >= 0.8
    assert cluster.zone is not None
    assert cluster.gex_level is not None
