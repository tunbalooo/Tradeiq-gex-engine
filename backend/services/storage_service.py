import logging
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.core.time_utils import ensure_utc, utc_iso
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
                    "created_at": utc_iso(row.created_at),
                    "candle_time": utc_iso(row.candle_time),
                    "previous_state": row.previous_state,
                    "new_state": row.new_state,
                    "price": row.price,
                    "detail": row.detail,
                } for row in rows]
        except Exception:
            logger.exception("Unable to read setup timeline")
            return []

    @staticmethod
    def _history_payload(record: TradeSetupRecord) -> dict:
        snapshot = record.setup_snapshot or {}
        return {
            "setup_id": record.setup_id,
            "created_at": utc_iso(record.created_at),
            "updated_at": utc_iso(record.updated_at),
            "symbol": record.symbol,
            "direction": record.direction,
            "confidence": record.confidence,
            "confidence_grade": snapshot.get("confidence_grade", "—"),
            "trade_grade": snapshot.get("trade_grade", "—"),
            "quality_stage": snapshot.get("quality_stage", "LOCATION_ONLY"),
            "location_quality_score": snapshot.get("location_quality_score", 0),
            "confirmation_quality_score": snapshot.get("confirmation_quality_score", 0),
            "execution_quality_score": snapshot.get("execution_quality_score", 0),
            "trade_quality_score": snapshot.get("trade_quality_score", 0),
            "primary_entry_model": snapshot.get("primary_entry_model"),
            "trigger_entry_model": snapshot.get("trigger_entry_model") or snapshot.get("primary_entry_model"),
            "trigger_entry_model_key": snapshot.get("trigger_entry_model_key") or snapshot.get("primary_entry_model_key"),
            "thesis_fingerprint": snapshot.get("thesis_fingerprint"),
            "structure_event_key": snapshot.get("structure_event_key"),
            "primary_model_score": snapshot.get("primary_model_score", 0),
            "entry": record.entry,
            "stop_loss": record.stop_loss,
            "active_stop_loss": snapshot.get("active_stop_loss"),
            "take_profit_1": record.take_profit_1,
            "take_profit_2": record.take_profit_2,
            "risk_reward": record.risk_reward,
            "status": record.status,
            "order_state": record.order_state,
            "management_state": snapshot.get("management_state", "FLAT"),
            "outcome": record.outcome,
            "result_r": record.result_r,
            "mfe_points": snapshot.get("max_favorable_excursion_points", 0),
            "mae_points": snapshot.get("max_adverse_excursion_points", 0),
            "target_sources": record.target_sources or {},
            "watch_trigger": snapshot.get("watch_trigger"),
            "watch_phase": snapshot.get("watch_phase"),
            "last_transition_reason": snapshot.get("last_transition_reason"),
            "armed_at": utc_iso(record.armed_at),
            "filled_at": utc_iso(record.filled_at),
            "closed_at": utc_iso(record.closed_at),
        }

    @staticmethod
    def _scan_signature(record: TradeSetupRecord) -> tuple:
        snapshot = record.setup_snapshot or {}
        fingerprint = snapshot.get("thesis_fingerprint")
        if fingerprint:
            return (record.symbol, fingerprint)
        trigger_model = snapshot.get("trigger_entry_model_key") or snapshot.get("primary_entry_model_key") or snapshot.get("primary_entry_model")
        structure_key = snapshot.get("structure_event_key") or "LEGACY"
        location = snapshot.get("watch_trigger")
        if location is None:
            low, high = snapshot.get("cluster_low"), snapshot.get("cluster_high")
            if low is not None and high is not None:
                location = (float(low) + float(high)) / 2
        if location is None:
            location = record.entry
        bucket = round(float(location) / 5.0) if location is not None else None
        return (record.symbol, record.direction, trigger_model, bucket, structure_key)

    @staticmethod
    def _is_published_trade(record: TradeSetupRecord) -> bool:
        snapshot = record.setup_snapshot or {}
        return bool(record.armed_at or record.filled_at or snapshot.get("armed_at") or snapshot.get("filled_at"))

    @staticmethod
    def _is_filled_trade(record: TradeSetupRecord) -> bool:
        snapshot = record.setup_snapshot or {}
        return bool(record.filled_at or snapshot.get("filled_at"))

    def recent_trades(self, limit: int = 100) -> list[dict]:
        """Return the execution/trade log only.

        Scanner-only watches, invalidations and expiries are intentionally kept
        out of this table so performance is not polluted by non-trades.
        """
        try:
            with SessionLocal() as db:
                rows = list(db.scalars(
                    select(TradeSetupRecord)
                    .order_by(TradeSetupRecord.updated_at.desc())
                    .limit(max(limit * 8, limit))
                ))
            results = []
            for record in rows:
                if not self._is_published_trade(record):
                    continue
                results.append(self._history_payload(record))
                if len(results) >= limit:
                    break
            return results
        except Exception:
            logger.exception("Unable to read trade history")
            return []

    def recent_setups(self, limit: int = 100) -> list[dict]:
        """Backward-compatible combined lifecycle history.

        New clients should use recent_trades and recent_scans separately.
        """
        rows = self.recent_trades(limit) + self.recent_scans(limit)
        rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return rows[:limit]

    def recent_scans(self, limit: int = 100) -> list[dict]:
        """Return one row per unique scanner thesis, newest lifecycle state first.

        Historical timer-generated duplicates are collapsed by the deterministic
        thesis fingerprint (or a legacy location/model signature).
        """
        try:
            with SessionLocal() as db:
                rows = list(db.scalars(
                    select(TradeSetupRecord)
                    .order_by(TradeSetupRecord.updated_at.desc())
                    .limit(max(limit * 12, limit))
                ))
            results = []
            seen: set[tuple] = set()
            for record in rows:
                if self._is_published_trade(record):
                    continue
                snapshot = record.setup_snapshot or {}
                meaningful = bool(
                    record.order_state != "PREVIEW_ONLY"
                    or snapshot.get("watch_started_at")
                    or snapshot.get("last_transition_to")
                )
                if not meaningful:
                    continue
                signature = self._scan_signature(record)
                if signature in seen:
                    continue
                seen.add(signature)
                results.append(self._history_payload(record))
                if len(results) >= limit:
                    break
            return results
        except Exception:
            logger.exception("Unable to read scanner history")
            return []

    def recent_terminal_theses(self, symbol: str | None = None, limit: int = 30) -> list[dict]:
        """Load persisted terminal thesis locks after a Railway/server restart."""
        terminal = {"TP2_HIT", "STOPPED", "EXPIRED", "INVALIDATED", "UNCONFIRMED_TOUCH"}
        try:
            with SessionLocal() as db:
                statement = select(TradeSetupRecord).where(TradeSetupRecord.order_state.in_(terminal))
                if symbol:
                    statement = statement.where(TradeSetupRecord.symbol == symbol)
                rows = list(db.scalars(statement.order_by(TradeSetupRecord.updated_at.desc()).limit(max(1, limit))))
            results = []
            for record in rows:
                snapshot = record.setup_snapshot or {}
                fingerprint = snapshot.get("thesis_fingerprint")
                if not fingerprint:
                    continue
                results.append({
                    "fingerprint": fingerprint,
                    "locked_at": ensure_utc(record.updated_at),
                    "state": record.order_state,
                    "outcome": record.outcome,
                    "setup_id": record.setup_id,
                    "structure_event_key": snapshot.get("structure_event_key"),
                    "direction": record.direction,
                    "trigger_model": snapshot.get("trigger_entry_model") or snapshot.get("primary_entry_model"),
                    "entry": snapshot.get("watch_trigger") if snapshot.get("watch_trigger") is not None else record.entry,
                    "cluster_low": snapshot.get("cluster_low"),
                    "cluster_high": snapshot.get("cluster_high"),
                })
            return results
        except Exception:
            logger.exception("Unable to restore terminal thesis locks")
            return []

    def recent_alerts(self, limit: int = 50) -> list[AlertItem]:
        try:
            with SessionLocal() as db:
                rows = list(db.scalars(select(AlertRecord).order_by(AlertRecord.created_at.desc()).limit(limit)))
                items = []
                for r in rows:
                    created_at = ensure_utc(r.created_at)
                    items.append(AlertItem(
                        time=created_at.strftime("%H:%M:%S UTC") if created_at else "—",
                        title=r.title,
                        detail=r.detail,
                        severity=r.severity if r.severity in {"positive", "negative", "warning", "info"} else "info",
                        created_at=created_at,
                    ))
                return items
        except Exception:
            return []

    def performance(self) -> PerformanceSummary:
        try:
            with SessionLocal() as db:
                candidates = list(db.scalars(
                    select(TradeSetupRecord)
                    .where(TradeSetupRecord.result_r.is_not(None))
                    .order_by(TradeSetupRecord.closed_at.asc())
                ))
            rows = [record for record in candidates if self._is_filled_trade(record)]
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
