from datetime import datetime, timedelta, timezone

from backend.models.schemas import Candle, EntryModelScore
from backend.services.decision_brain import decision_brain_service
from backend.services.setup_service import build_candidate_setup
from backend.services.trade_engine import TradeEngineService
from engine.adaptive_execution import select_execution
from engine.institutional_cluster import build_cluster_score


def test_cluster_requires_independent_categories_not_raw_label_count():
    ranking = [EntryModelScore(key="OTE_RETRACEMENT", name="OTE Retracement", direction="SHORT", score=88, eligible=True)]
    weak = build_cluster_score({"ote_overlap": True, "fib_pullback_touched": True}, ranking, 0.9)
    assert weak["eligible"] is False
    strong = build_cluster_score({
        "ote_overlap": True,
        "gex_alignment": True,
        "supply_demand": True,
        "liquidity_sweep": True,
        "displacement": True,
        "trend_alignment": True,
    }, ranking, 0.9)
    assert strong["eligible"] is True
    assert strong["score"] >= 72


def test_market_execution_selected_for_fresh_confirmed_cluster():
    decision = select_execution(
        model_key="INSTITUTIONAL_CONFLUENCE_CLUSTER",
        direction="SHORT",
        current_price=100.0,
        ideal_entry=100.5,
        atr=10.0,
        tick_size=0.25,
        model_confirmed=True,
        entry_valid=True,
        target_not_blocked=True,
        tp1=90.0,
        tp2=80.0,
        tp2_r=2.0,
        composite_score=94.0,
    )
    assert decision.execution_type == "MARKET"
    assert decision.executable is True


def test_no_execution_when_target_already_reached():
    decision = select_execution(
        model_key="OTE_RETRACEMENT",
        direction="SHORT",
        current_price=89.0,
        ideal_entry=100.0,
        atr=10.0,
        tick_size=0.25,
        model_confirmed=True,
        entry_valid=True,
        target_not_blocked=True,
        tp1=90.0,
        tp2=80.0,
        tp2_r=2.0,
    )
    assert decision.execution_type == "NONE"
    assert "target" in decision.reason.lower()


def test_market_execution_fills_immediately(monkeypatch):
    service = TradeEngineService()
    setup = build_candidate_setup()
    now = datetime.now(timezone.utc)
    candle = Candle(time=now, open=100, high=101, low=99, close=100, volume=10)
    candidate = setup.model_copy(update={
        "direction": "LONG",
        "actionable": True,
        "execution_type": "MARKET",
        "execution_reason": "Confirmed cluster remains fresh.",
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit_1": 105.0,
        "take_profit_2": 110.0,
        "tp1_r": 1.0,
        "tp2_r": 2.0,
        "risk_reward": 2.0,
    })
    armed = service._arm_candidate(candidate, candle)
    assert armed.order_state == "FILLED"
    assert armed.filled_at is not None
    assert armed.entry == 100.0


def test_waiting_order_expires_when_target_reached_before_fill(monkeypatch):
    service = TradeEngineService()
    setup = build_candidate_setup()
    t0 = datetime.now(timezone.utc)
    armed_candle = Candle(time=t0, open=100, high=101, low=99, close=100, volume=10)
    candidate = setup.model_copy(update={
        "direction": "SHORT",
        "actionable": True,
        "execution_type": "LIMIT",
        "entry": 110.0,
        "stop_loss": 115.0,
        "take_profit_1": 100.0,
        "take_profit_2": 95.0,
        "tp1_r": 2.0,
        "tp2_r": 3.0,
        "risk_reward": 3.0,
    })
    armed = service._arm_candidate(candidate, armed_candle)
    later = Candle(time=t0 + timedelta(minutes=1), open=101, high=102, low=98, close=99, volume=20)
    expired = service._advance(armed, candidate, later)
    assert expired.order_state == "EXPIRED"
    assert expired.outcome == "TARGET_REACHED_BEFORE_FILL"
