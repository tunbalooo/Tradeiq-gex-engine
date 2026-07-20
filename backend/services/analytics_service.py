"""Performance analytics derived from persisted deterministic setup records."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.db_models import TradeSetupRecord


class AnalyticsService:
    def summary(self, limit: int = 1000) -> dict:
        with SessionLocal() as db:
            rows = list(db.scalars(
                select(TradeSetupRecord)
                .order_by(TradeSetupRecord.updated_at.desc())
                .limit(max(1, min(limit, 5000)))
            ))

        model_groups: dict[str, list[float]] = defaultdict(list)
        outcomes: dict[str, int] = defaultdict(int)
        cancellations: dict[str, int] = defaultdict(int)
        completed = 0
        for row in rows:
            snapshot = row.setup_snapshot or {}
            model = snapshot.get("primary_entry_model") or "Unclassified"
            if row.result_r is not None:
                model_groups[model].append(float(row.result_r))
                completed += 1
            outcome = row.outcome or row.order_state or "UNKNOWN"
            outcomes[outcome] += 1
            if row.order_state in {"EXPIRED", "INVALIDATED", "UNCONFIRMED_TOUCH"} or outcome in {"WATCH_EXPIRED", "CONFLUENCE_LOST", "OPPOSITE_SETUP"}:
                cancellations[outcome] += 1

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
            "setups_considered": len(rows),
            "completed_results": completed,
            "model_leaderboard": leaderboard,
            "outcomes": dict(sorted(outcomes.items())),
            "cancellations": dict(sorted(cancellations.items())),
            "note": "Analytics are descriptive. They do not change live model scores or trade decisions.",
        }


analytics_service = AnalyticsService()
