from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.main import app
from backend.models.schemas import Candle
from backend.services.instruments import get_instrument
from backend.services.setup_service import _cross_market_alignment
from engine.institutional_cluster import build_cluster_score
from engine.market_structure import analyze_market_structure


def _candle(i, o, h, l, c, v=100, base=datetime(2024, 1, 1, tzinfo=timezone.utc)):
    return Candle(time=base + timedelta(minutes=i), open=o, high=h, low=l, close=c, volume=v)


def _flat_run(count, price, start=0):
    return [_candle(start + i, price, price + 0.3, price - 0.3, price) for i in range(count)]


def test_inverse_fvg_detected_on_reclaim_and_cleared_on_failure():
    candles = _flat_run(45, 100.0)
    # Bearish FVG: candle[47].high < candle[45].low -> zone (98.0-99.2ish)
    candles.append(_candle(45, 100.0, 99.6, 99.2, 99.4))
    candles.append(_candle(46, 99.4, 99.5, 99.0, 99.1))
    candles.append(_candle(47, 99.1, 99.0, 98.0, 98.2))
    candles += _flat_run(7, 98.2, start=48)
    # Reclaim candle closes back above the bearish FVG zone -> becomes a bullish inverse FVG.
    candles.append(_candle(55, 98.2, 99.6, 98.1, 99.5))
    candles += _flat_run(6, 99.5, start=56)

    structure = analyze_market_structure(candles)
    assert structure["bullish_inverse_fvg"] is True
    assert structure["bullish_inverse_fvg_low"] is not None
    assert structure["bullish_inverse_fvg_high"] is not None
    assert structure["bearish_inverse_fvg"] is False

    # A later close back through the zone's low invalidates the inversion.
    failed = list(candles) + [_candle(62, 99.5, 99.6, 97.5, 97.8)]
    structure_after_failure = analyze_market_structure(failed)
    assert structure_after_failure["bullish_inverse_fvg"] is False


def test_htf_and_cross_market_are_independent_confluence_categories():
    # Only multi-timeframe structure aligns; cross-market is absent. It must
    # still count as its own independent active category, not require the other.
    only_htf = {"htf_alignment": True}
    cluster = build_cluster_score(only_htf, ranking=[], cluster_score=0.0)
    assert "mtf_structure" in cluster["active_categories"]
    assert "cross_market" not in cluster["active_categories"]

    # And the reverse: only cross-market aligns.
    only_cross_market = {"cross_market_alignment": True}
    cluster = build_cluster_score(only_cross_market, ranking=[], cluster_score=0.0)
    assert "cross_market" in cluster["active_categories"]
    assert "mtf_structure" not in cluster["active_categories"]

    # Both together simply stack, as two separate factors.
    both = {"htf_alignment": True, "cross_market_alignment": True}
    cluster = build_cluster_score(both, ranking=[], cluster_score=0.0)
    assert {"mtf_structure", "cross_market"} <= set(cluster["active_categories"])


def test_cross_market_alignment_has_a_correlate_for_nq_es_but_not_gold():
    nq_profile = get_instrument("NQ")
    symbol, trend, aligned = _cross_market_alignment(nq_profile, "LONG")
    assert symbol == "ES"
    assert trend in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert isinstance(aligned, bool)

    gc_profile = get_instrument("GC")
    symbol, trend, aligned = _cross_market_alignment(gc_profile, "LONG")
    assert symbol is None
    assert aligned is False


def test_best_setup_endpoint_ranks_across_scanned_symbols():
    with TestClient(app) as client:
        scan = client.post("/api/multi-market/scan")
        assert scan.status_code == 200
        response = client.get("/api/best-setup")

    assert response.status_code == 200
    payload = response.json()
    assert "best" in payload
    assert "alternatives" in payload
    assert payload["candidates_considered"] >= 1
    if payload["best"] is not None:
        best = payload["best"]
        for key in ("symbol", "direction", "actionable", "trade_quality_score", "trade_grade", "model_score", "confidence"):
            assert key in best
        # Higher-ranked alternatives never outrank the chosen best setup.
        for alt in payload["alternatives"]:
            assert (1 if alt["actionable"] else 0, alt["trade_quality_score"]) <= (
                1 if best["actionable"] else 0, best["trade_quality_score"]
            )
