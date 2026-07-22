from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.models.schemas import (
    Candle,
    FibLevel,
    GexSummary,
    MarketMapCluster,
    Zone,
)
from engine.confluence_cluster import ClusterResult
from engine.institutional_level_map import build_institutional_market_map
from engine.risk_engine import build_trade_levels


ROOT = Path(__file__).resolve().parents[1]
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
ROUTES = (ROOT / "backend" / "api" / "routes.py").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _candle(index: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        time=datetime(2026, 7, 22, tzinfo=timezone.utc) + timedelta(minutes=index * 5),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def _gex(*, put_wall: float = 99.5, call_wall: float = 112.0) -> GexSummary:
    return GexSummary(
        regime="POSITIVE",
        gamma_flip=100.0,
        put_wall=put_wall,
        call_wall=call_wall,
        net_gex=1.0,
        levels=[],
        gamma_support=put_wall,
        gamma_resistance=call_wall,
        max_pain=105.0,
    )


def test_map_groups_independent_levels_into_a_major_rejecting_support_cluster():
    candles = [
        _candle(0, 101.0, 102.0, 100.5, 101.0),
        _candle(1, 101.0, 101.5, 98.8, 99.2),
        _candle(2, 99.2, 102.0, 99.0, 101.8),
    ]
    market_map = build_institutional_market_map(
        current_price=101.8,
        atr=10.0,
        tick_size=0.25,
        candles=candles,
        gex=_gex(),
        zones=[
            Zone(
                timeframe="1H",
                kind="DEMAND",
                low=98.8,
                high=100.2,
                strength=5,
                fresh=True,
                displacement_score=1.2,
            )
        ],
        fib_levels=[FibLevel(ratio=0.705, price=99.4, label="Ideal OTE")],
        vwap=100.1,
        std_low=98.0,
        std_high=104.0,
        session_low=97.0,
        session_high=110.0,
        previous_liquidity_low=99.0,
        previous_liquidity_high=108.0,
        direction="LONG",
    )

    active = market_map.active_cluster
    assert active is not None
    assert active.role == "SUPPORT"
    assert active.state == "REJECTING"
    assert active.tier == "MAJOR"
    assert active.actionable_location is True
    assert active.independent_categories >= 4
    assert {"GEX", "ZONE", "RETRACEMENT", "LIQUIDITY"}.issubset(set(active.source_groups))


def test_acceptance_through_a_cluster_disables_it_as_an_entry_location():
    candles = [
        _candle(0, 99.0, 100.2, 98.8, 99.5),
        _candle(1, 99.5, 103.0, 99.4, 102.0),
        _candle(2, 102.0, 104.0, 101.8, 103.0),
    ]
    market_map = build_institutional_market_map(
        current_price=103.0,
        atr=5.0,
        tick_size=0.25,
        candles=candles,
        gex=_gex(put_wall=90.0, call_wall=100.0),
        zones=[
            Zone(
                timeframe="5m",
                kind="SUPPLY",
                low=99.5,
                high=100.5,
                strength=5,
                fresh=True,
                displacement_score=1.2,
            )
        ],
        fib_levels=[],
        vwap=98.0,
        std_low=95.0,
        std_high=100.0,
        session_low=90.0,
        session_high=100.0,
        previous_liquidity_low=92.0,
        previous_liquidity_high=100.0,
        direction="LONG",
    )

    accepted = next(item for item in market_map.ladder if item.role == "RESISTANCE")
    assert accepted.state == "ACCEPTING"
    assert accepted.accepted_through is True
    assert accepted.actionable_location is False
    assert market_map.active_cluster is None


def test_market_map_cluster_is_used_as_real_opposing_liquidity_target():
    gex = GexSummary(
        regime="POSITIVE",
        gamma_flip=100.0,
        put_wall=90.0,
        call_wall=130.0,
        net_gex=1.0,
        levels=[],
    )
    resistance = MarketMapCluster(
        cluster_id="resistance-map",
        role="RESISTANCE",
        low=110.0,
        high=111.0,
        midpoint=110.5,
        score=85.0,
        tier="STRONG",
        state="APPROACHING",
        distance_points=10.0,
        distance_atr=1.0,
        independent_categories=3,
        source_groups=["GEX", "ZONE", "LIQUIDITY"],
    )
    levels = build_trade_levels(
        direction="LONG",
        current_price=105.0,
        ote_low=98.0,
        ote_high=102.0,
        ideal_ote=100.0,
        zones=[],
        atr=10.0,
        cluster=ClusterResult(0.0, None, None, None, None, None, False, False),
        gex=gex,
        previous_liquidity_high=140.0,
        previous_liquidity_low=90.0,
        session_high=135.0,
        session_low=95.0,
        tick_size=0.25,
        preferred_entry=100.0,
        preferred_invalidation=95.0,
        market_map_clusters=[resistance],
    )

    assert levels["take_profit_1"] == 110.0
    assert "Institutional Resistance Cluster" in levels["target_sources"]["tp1"]
    assert levels["target_sources"]["nearest_barrier"] == levels["target_sources"]["tp1"]


def test_clean_chart_uses_ranked_map_instead_of_every_raw_level():
    assert "function renderCleanMarketMapLines(instance, setup)" in CHART
    assert 'add(map.active_cluster, "ACTIVE CLUSTER", false);' in CHART
    assert 'add(map.opposing_cluster, "OPPOSING LIQUIDITY", true);' in CHART
    assert "if (marketMapVisible && renderCleanMarketMapLines(instance, setup)) return;" in CHART
    assert "market-map-ladder" in APP


def test_market_map_api_and_v313_version_are_exposed():
    assert '@router.get("/market-map")' in ROUTES
    assert "3.1.3-institutional-market-map" in MAIN
    assert "tradeiq-v3.1.3-institutional-market-map-shell" in SW
    assert "?v=313" in SW
