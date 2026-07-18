import logging
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.db_models import AlertRecord, SetupTransitionRecord, TradeSetupRecord
from backend.models.schemas import AlertItem, PerformanceSummary, TradeSetup

logger = logging.getLogger(__name__)


class StorageService:
    def save_setup(self, setup: TradeSetup, result_r: float | None = None) -> None:
        try:
            with SessionLocal() as db:
                record = db.scalar(select(TradeSetupRecord).where(TradeSetupRecord.setup_id == setup.setup_id))
                payload = setup.model_dump(mode="json")
                if record is None:
                    record = TradeSetupRecord(setup_id=setup.setup_id, direction=setup.direction, confidence=setup.confidence)
                    db.add(record)
                record.updated_at = datetime.now(timezone.utc)
                record.valid_until = setup.valid_until
                record.armed_at = setup.armed_at
                record.filled_at = setup.filled_at
                record.closed_at = setup.closed_at
                record.symbol = setup.symbol
                record.direction = setup.direction
                record.confidence = setup.confidence
                record.actionable = setup.actionable
                record.entry = setup.entry
                record.stop_loss = setup.stop_loss
                record.take_profit_1 = setup.take_profit_1
                record.take_profit_2 = setup.take_profit_2
                record.risk_reward = setup.risk_reward
                record.status = setup.status
                record.order_state = setup.order_state
                record.outcome = setup.outcome
                if result_r is not None:
                    record.result_r = result_r
                record.target_sources = setup.target_sources
                record.confidence_components = setup.confidence_components
                record.signals = setup.signals
                record.gex_snapshot = setup.gex.model_dump(mode="json")
                record.setup_snapshot = payload
                db.commit()
        except Exception:
            logger.exception("Unable to persist setup")

    def transition(self, setup: TradeSetup, previous: str | None, new: str, price: float | None, candle_time, detail: str, severity: str = "info") -> None:
        try:
            with SessionLocal() as db:
                db.add(SetupTransitionRecord(setup_id=setup.setup_id, candle_time=candle_time, previous_state=previous, new_state=new, price=price, detail=detail))
                db.add(AlertRecord(setup_id=setup.setup_id, title=new.replace("_", " ").title(), detail=detail, severity=severity))
                db.commit()
        except Exception:
            logger.exception("Unable to persist lifecycle transition")

    def recent_setups(self, limit: int = 100) -> list[dict]:
        try:
            with SessionLocal() as db:
                rows = list(db.scalars(select(TradeSetupRecord).order_by(TradeSetupRecord.updated_at.desc()).limit(limit)))
                return [{
                    "setup_id": r.setup_id, "created_at": r.created_at, "updated_at": r.updated_at,
                    "direction": r.direction, "confidence": r.confidence, "entry": r.entry,
                    "stop_loss": r.stop_loss, "take_profit_1": r.take_profit_1,
                    "take_profit_2": r.take_profit_2, "risk_reward": r.risk_reward,
                    "status": r.status, "order_state": r.order_state, "outcome": r.outcome,
                    "result_r": r.result_r, "target_sources": r.target_sources or {},
                } for r in rows]
        except Exception:
            logger.exception("Unable to read setup history")
            return []

    def recent_alerts(self, limit: int = 50) -> list[AlertItem]:
        try:
            with SessionLocal() as db:
                rows = list(db.scalars(select(AlertRecord).order_by(AlertRecord.created_at.desc()).limit(limit)))
                return [AlertItem(time=r.created_at.astimezone().strftime("%H:%M:%S"), title=r.title, detail=r.detail, severity=r.severity if r.severity in {"positive", "negative", "warning", "info"} else "info", created_at=r.created_at) for r in rows]
        except Exception:
            return []

    def performance(self) -> PerformanceSummary:
        try:
            with SessionLocal() as db:
                rows = list(db.scalars(select(TradeSetupRecord).where(TradeSetupRecord.result_r.is_not(None)).order_by(TradeSetupRecord.closed_at.asc())))
        except Exception:
            rows = []
        if not rows:
            return PerformanceSummary(win_rate=0, trades=0, average_r=0, profit_factor=0, net_pnl=0, equity_curve=[0, 0], simulated=True)
        results = [float(r.result_r) for r in rows if r.result_r is not None]
        wins = [r for r in results if r > 0]
        losses = [r for r in results if r < 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        equity, total = [0.0], 0.0
        for result in results:
            total += result
            equity.append(round(total, 2))
        return PerformanceSummary(
            win_rate=round(len(wins) / len(results) * 100, 1), trades=len(results),
            average_r=round(sum(results) / len(results), 2),
            profit_factor=round(gross_win / gross_loss, 2) if gross_loss else (gross_win if gross_win else 0),
            net_pnl=round(sum(results), 2), equity_curve=equity, simulated=False,
        )


storage_service = StorageService()
