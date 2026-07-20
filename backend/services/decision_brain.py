"""Central deterministic coordinator for TradeIQ v3.0.

The brain selects and explains an entry model. It never asks Claude to make a
trading decision, and it cannot bypass the existing market, risk or lifecycle
safety gates.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.core.config import settings
from backend.models.schemas import EntryModelScore, TradeSetup


class DecisionBrainService:
    def select(self, setup: TradeSetup, ranking: list[EntryModelScore]) -> TradeSetup:
        eligible = [item for item in ranking if item.eligible]
        primary = eligible[0] if eligible else (ranking[0] if ranking else None)
        alternatives = eligible[1:4]

        if primary is None:
            return setup.model_copy(update={
                "primary_entry_model": None,
                "entry_model_scores": [],
                "alternative_entry_models": [],
                "model_selection_reason": "No entry model produced sufficient deterministic evidence.",
                "actionable": False,
            })

        model_gate = primary.eligible and primary.score >= settings.entry_model_min_score
        actionable = bool(setup.actionable and model_gate)
        if primary.eligible:
            reason = (
                f"{primary.name} ranks first at {primary.score:.1f}%. "
                f"The engine retained {len(alternatives)} qualified backup model(s)."
            )
        else:
            reason = (
                f"{primary.name} is currently the strongest developing model at {primary.score:.1f}%, "
                f"but it is missing: {', '.join(primary.missing) or 'mandatory confirmation'}."
            )

        status = setup.status
        order_state = setup.order_state
        if setup.actionable and not actionable:
            status = "DEVELOPING"
            order_state = "PREVIEW_ONLY"

        return setup.model_copy(update={
            "primary_entry_model": primary.name,
            "primary_entry_model_key": primary.key,
            "primary_model_score": primary.score,
            "entry_model_scores": ranking,
            "alternative_entry_models": [item.name for item in alternatives],
            "model_selection_reason": reason,
            "model_selected_at": datetime.now(timezone.utc),
            "actionable": actionable,
            "status": status,
            "order_state": order_state,
            "signals": {
                **setup.signals,
                "entry_model_gate": model_gate,
                "primary_model_key": primary.key,
            },
        })

    def snapshot(self, setup: TradeSetup | None) -> dict:
        if setup is None:
            return {"status": "STARTING", "primary": None, "alternatives": [], "models": []}
        return {
            "status": setup.order_state,
            "setup_id": setup.setup_id,
            "direction": setup.direction,
            "primary": {
                "name": setup.primary_entry_model,
                "key": setup.primary_entry_model_key,
                "score": setup.primary_model_score,
                "reason": setup.model_selection_reason,
            },
            "alternatives": setup.alternative_entry_models,
            "confidence": {
                "score": setup.confidence,
                "grade": setup.confidence_grade,
                "categories": setup.institutional_confidence_components,
            },
            "models": [item.model_dump(mode="json") for item in setup.entry_model_scores],
        }


decision_brain_service = DecisionBrainService()
