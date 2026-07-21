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


    def save_alert(self, title: str, detail: str, severity: str = "info", setup_id: str | None = None) -> None:
        """Persist a non-lifecycle alert such as a background market-radar event."""
        safe_severity = severity if severity in {"positive", "negative", "warning", "info"} else "info"
        try:
            with SessionLocal() as db:
                db.add(AlertRecord(setup_id=setup_id, title=title[:120], detail=detail, severity=safe_severity))
                db.commit()
        except Exception:
            logger.exception("Unable to persist alert")

    def load_active_setup(self, symbol: str | None = None) -> TradeSetup | None:
        """Restore the newest non-terminal setup after a server restart.

        The complete validated TradeSetup is persisted in setup_snapshot. Claude,
        the UI and the trade engine therefore resume the same lifecycle object
        instead of silently creating a new setup after every deployment.
        """
        active_states = {"WATCHING", "WAITING_FOR_LIMIT", "FILLED", "TP1_HIT"}
        try:
            with SessionLocal() as db:
                statement = select(TradeSetupRecord).where(
                    TradeSetupRecord.order_state.in_(active_states),
                    TradeSetupRecord.closed_at.is_(None),
                )
                if symbol:
                    statement = statement.where(TradeSetupRecord.symbol == symbol)
                record = db.scalar(statement.order_by(TradeSetupRecord.updated_at.desc()).limit(1))
                if record is None or not record.setup_snapshot:
                    return None
                setup = TradeSetup.model_validate(record.setup_snapshot)
                if setup.order_state not in active_states or setup.closed_at is not None:
                    return None
                return setup
        except Exception:
            logger.exception("Unable to restore active setup")
            return None

    def setup_timeline(self, setup_id: str, limit: int = 100) -> list[dict]:
        """Return deterministic lifecycle transitions in chronological order."""
        try:
            with SessionLocal() as db:
                rows = list(db.scalars(
                    select(SetupTransitionRecord)
                    .where(SetupTransitionRecord.setup_id == setup_id)
                    .order_by(SetupTransitionRecord.created_at.desc())
                    .limit(max(1, min(limit, 500)))
                ))
                rows.reverse()
                return [{
                    "created_at": row.created_at,
                    "candle_time": row.candle_time,
                    "previous_state": row.previous_state,
                    "new_state": row.new_state,
                    "price": row.price,
                    "detail": row.detail,
                } for row in rows]
        except Exception:
            logger.exception("Unable to read setup timeline")
            return []

    def recent_setups(self, limit: int = 100) -> list[dict]:
        try:
            with SessionLocal() as db:
                # Fetch extra rows because preview/scanning records are intentionally
                # hidden from Setup History. The page now represents actual lifecycle
                # candidates, not every transient engine refresh.
                rows = list(db.scalars(
                    select(TradeSetupRecord)
                    .order_by(TradeSetupRecord.updated_at.desc())
                    .limit(max(limit * 5, limit))
                ))
                results = []
                seen_recent: dict[tuple, datetime] = {}
                for r in rows:
                    snapshot = r.setup_snapshot or {}
                    meaningful = bool(
                        r.order_state != "PREVIEW_ONLY"
                        or snapshot.get("watch_started_at")
                        or r.armed_at
                        or r.filled_at
                        or r.closed_at
                    )
                    if not meaningful:
                        continue
                    signature = (
                        r.symbol, r.direction, snapshot.get("primary_entry_model"), r.order_state,
                        round(float(r.entry), 2) if r.entry is not None else round(float(snapshot.get("watch_trigger")), 2) if snapshot.get("watch_trigger") is not None else None,
                    )
                    prior = seen_recent.get(signature)
                    if prior and abs((prior - r.updated_at).total_seconds()) < 45:
                        continue
                    seen_recent[signature] = r.updated_at
                    results.append({
                        "setup_id": r.setup_id, "created_at": r.created_at, "updated_at": r.updated_at,
                        "symbol": r.symbol, "direction": r.direction, "confidence": r.confidence,
                        "confidence_grade": snapshot.get("confidence_grade", "—"),
                        "primary_entry_model": snapshot.get("primary_entry_model"),
                        "primary_model_score": snapshot.get("primary_model_score", 0),
                        "entry": r.entry, "stop_loss": r.stop_loss,
                        "active_stop_loss": snapshot.get("active_stop_loss"),
                        "take_profit_1": r.take_profit_1, "take_profit_2": r.take_profit_2,
                        "risk_reward": r.risk_reward, "status": r.status,
                        "order_state": r.order_state, "management_state": snapshot.get("management_state", "FLAT"),
                        "outcome": r.outcome, "result_r": r.result_r,
                        "mfe_points": snapshot.get("max_favorable_excursion_points", 0),
                        "mae_points": snapshot.get("max_adverse_excursion_points", 0),
                        "target_sources": r.target_sources or {},
                    })
                    if len(results) >= limit:
                        break
                return results
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
