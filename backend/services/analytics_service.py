"""Performance analytics derived from persisted deterministic setup records."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.db_models import TradeSetupRecord


class AnalyticsService:
    @staticmethod
    def _is_trade(row: TradeSetupRecord) -> bool:
        snapshot = row.setup_snapshot or {}
        return bool(row.filled_at or snapshot.get("filled_at"))

    def summary(self, limit: int = 1000) -> dict:
        with SessionLocal() as db:
            rows = list(db.scalars(
                select(TradeSetupRecord)
                .order_by(TradeSetupRecord.updated_at.desc())
                .limit(max(1, min(limit, 5000)))
            ))

        model_groups: dict[str, list[float]] = defaultdict(list)
        trade_outcomes: dict[str, int] = defaultdict(int)
        scan_outcomes: dict[str, int] = defaultdict(int)
        completed = 0
        trades_considered = 0
        scans_considered = 0
        for row in rows:
            snapshot = row.setup_snapshot or {}
            is_trade = self._is_trade(row)
            outcome = row.outcome or row.order_state or "UNKNOWN"
            if is_trade:
                trades_considered += 1
                trigger_model = snapshot.get("trigger_entry_model") or snapshot.get("primary_entry_model") or "Unclassified"
                if row.result_r is not None:
                    model_groups[trigger_model].append(float(row.result_r))
                    completed += 1
                trade_outcomes[outcome] += 1
            else:
                scans_considered += 1
                if row.order_state != "PREVIEW_ONLY" or snapshot.get("watch_started_at"):
                    scan_outcomes[outcome] += 1

        leaderboard = []
        for model, results in model_groups.items():
            wins = [value for value in results if value > 0]
            losses = [value for value in results if value < 0]
            leaderboard.append({
                "model": model,
                "trades": len(results),
                "win_rate": round(len(wins) / len(results) * 100, 1) if results else 0.0,
                "average_r": round(sum(results) / len(results), 2) if results else 0.0,
                "net_r": round(sum(results), 2),
                "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else round(sum(wins), 2),
            })
        leaderboard.sort(key=lambda item: (item["average_r"], item["win_rate"], item["trades"]), reverse=True)
        return {
            "records_considered": len(rows),
            "trades_considered": trades_considered,
            "scans_considered": scans_considered,
            "completed_results": completed,
            "model_leaderboard": leaderboard,
            "trade_outcomes": dict(sorted(trade_outcomes.items())),
            "scan_outcomes": dict(sorted(scan_outcomes.items())),
            # Backward compatibility for older clients.
            "outcomes": dict(sorted(trade_outcomes.items())),
            "cancellations": dict(sorted(scan_outcomes.items())),
            "note": "Trade analytics contain published executions only. Scanner outcomes are reported separately and never counted as trades.",
        }


analytics_service = AnalyticsService()
