from datetime import datetime, timedelta, timezone
from backend.models.schemas import Candle
from backend.services.trade_engine import TradeEngineService
from backend.services.setup_service import build_candidate_setup


def test_armed_candle_cannot_retroactively_fill(monkeypatch):
    monkeypatch.setattr("backend.services.trade_engine.get_session_status", lambda: {"can_trade_now": True})
    service=TradeEngineService()
    candidate=build_candidate_setup()
    candidate=candidate.model_copy(update={"actionable":True,"entry_valid":True,"entry":candidate.entry or 100,"stop_loss":candidate.stop_loss or 90,"take_profit_1":candidate.take_profit_1 or 110,"take_profit_2":candidate.take_profit_2 or 120})
    now=datetime.now(timezone.utc)
    candle=Candle(time=now,open=100,high=200,low=0,close=100,volume=1)
    armed=service._maybe_arm(candidate,candle)
    same=service._advance(armed,candidate,candle)
    assert same.order_state=="WAITING_FOR_LIMIT"
