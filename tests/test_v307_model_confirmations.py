from datetime import datetime, timedelta, timezone

from backend.models.schemas import Candle, EntryModelScore
from backend.services.decision_brain import decision_brain_service
from backend.services.setup_service import build_candidate_setup
from engine.model_confirmations import evaluate_model_confirmations


def c(i, o, h, l, close):
    return Candle(
        time=datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc) + timedelta(minutes=5*i),
        open=o, high=h, low=l, close=close, volume=1000,
    )


def test_every_ranked_entry_model_has_an_explicit_confirmation_contract():
    candles = [
        c(0, 100, 102, 99, 101), c(1, 101, 104, 100, 103),
        c(2, 103, 106, 102, 105), c(3, 105, 106, 102, 103),
        c(4, 103, 107, 102, 106),
    ]
    signals = {
        "trend_alignment": True, "liquidity_sweep": True, "ordered_sequence": True,
        "fib_pullback_touched": True, "fib_pullback_confirmed": True,
        "fib_pullback_entry_fresh": True, "inverse_fvg": True,
        "inverse_fvg_mid": 103.0, "smt_divergence": True,
    }
    contracts = evaluate_model_confirmations(
        candles, direction="LONG", atr=3.0, vwap=103.0, gamma_flip=103.0,
        zone_low=102.0, zone_high=104.0, ote_low=102.0, ote_high=104.0,
        fvg_low=102.5, fvg_high=103.5, previous_liquidity_low=99.0,
        previous_liquidity_high=104.0, signals=signals,
    )
    expected = {
        "LIQUIDITY_SWEEP_MSS", "SUPPLY_DEMAND_RETEST", "OTE_RETRACEMENT",
        "FIB_PULLBACK_CONTINUATION", "GAMMA_FLIP_RECLAIM", "FVG_RETEST",
        "ORDER_BLOCK_RETEST", "EMA_PULLBACK", "VWAP_RECLAIM", "BREAK_RETEST",
        "TREND_CONTINUATION", "INVERSE_FVG", "SMT_DIVERGENCE",
    }
    assert set(contracts) == expected
    for contract in contracts.values():
        assert contract.label
        assert contract.window_bars >= 3
        assert isinstance(contract.evidence, list)
        assert isinstance(contract.missing, list)


def test_supply_demand_short_uses_zone_rejection_not_generic_sweep_gate():
    candles = [
        c(0, 110, 111, 108, 109), c(1, 109, 110, 106, 107),
        c(2, 107, 108, 104, 105), c(3, 105, 109, 104, 108),
        c(4, 108, 109, 103, 104),
    ]
    contracts = evaluate_model_confirmations(
        candles, direction="SHORT", atr=4.0, vwap=107.0, gamma_flip=108.0,
        zone_low=107.5, zone_high=109.0, ote_low=107.0, ote_high=109.0,
        fvg_low=106.5, fvg_high=108.0, previous_liquidity_low=104.0,
        previous_liquidity_high=110.0,
        signals={"trend_alignment": True, "liquidity_sweep": False},
    )
    result = contracts["SUPPLY_DEMAND_RETEST"]
    assert result.confirmed is True
    assert "supply/demand zone touched" in result.evidence
    assert "close away from zone" in result.evidence


def test_decision_brain_prefers_model_native_confirmation_payload():
    setup = build_candidate_setup()
    model = EntryModelScore(
        key="VWAP_RECLAIM", name="VWAP Reclaim", direction=setup.direction,
        score=90, eligible=True, trigger_price=setup.entry, invalidation_price=setup.stop_loss,
    )
    selected = decision_brain_service.select(setup.model_copy(update={
        "entry_valid": True, "confidence": 80, "tp2_r": 2.2,
        "signals": {
            **setup.signals,
            "target_not_blocked": True,
            "model_confirmations": {
                "VWAP_RECLAIM": {
                    "confirmed": False,
                    "label": "VWAP reclaimed and accepted",
                    "evidence": ["trend alignment"],
                    "missing": ["VWAP reclaim/hold"],
                    "window_bars": 3,
                }
            },
        },
    }), [model])
    assert selected.actionable is False
    assert selected.signals["entry_model_missing"] == ["VWAP reclaim/hold"]
