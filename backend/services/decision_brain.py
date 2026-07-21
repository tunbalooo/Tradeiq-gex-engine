"""Central deterministic coordinator for TradeIQ v3.0.3.

The Decision Brain selects the strongest entry model and applies model-specific
confirmation gates. Claude remains read-only. A universal liquidity-sequence
requirement is deliberately avoided because an OTE, EMA, VWAP or zone-retest
setup should be judged by its own deterministic evidence rather than by the
rules of a different model.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.core.config import settings
from backend.models.schemas import EntryModelScore, TradeSetup


MODEL_CONFIRMATIONS: dict[str, tuple[tuple[str, ...], ...]] = {
    # Every inner tuple is an OR group. Every group must have at least one true signal.
    "LIQUIDITY_SWEEP_MSS": (("liquidity_sweep",), ("displacement",), ("ordered_sequence",)),
    "SUPPLY_DEMAND_RETEST": (("supply_demand",), ("trend_alignment",), ("gex_ote_zone_cluster", "gex_alignment")),
    "OTE_RETRACEMENT": (("ote_overlap",), ("trend_alignment",), ("gex_ote_zone_cluster", "supply_demand"), ("displacement", "ordered_sequence")),
    "FIB_PULLBACK_CONTINUATION": (("fib_pullback_touched",), ("fib_pullback_rejection",), ("fib_pullback_entry_fresh",), ("trend_alignment",)),
    "GAMMA_FLIP_RECLAIM": (("gex_alignment",), ("trend_alignment",), ("displacement",), ("vwap_alignment",)),
    "FVG_RETEST": (("directional_fvg",), ("displacement",), ("trend_alignment",)),
    "ORDER_BLOCK_RETEST": (("supply_demand",), ("displacement",), ("trend_alignment",)),
    "EMA_PULLBACK": (("trend_alignment",), ("vwap_alignment",), ("displacement", "volume_expansion")),
    "VWAP_RECLAIM": (("vwap_alignment",), ("trend_alignment",), ("displacement",)),
    "BREAK_RETEST": (("displacement",), ("trend_alignment",), ("ordered_sequence",)),
    "TREND_CONTINUATION": (("trend_alignment",), ("displacement",), ("vwap_alignment", "volume_expansion")),
    "INVERSE_FVG": (("inverse_fvg",), ("displacement",), ("trend_alignment",)),
    "SMT_DIVERGENCE": (("smt_divergence",), ("liquidity_sweep", "displacement"), ("trend_alignment",)),
}


def _signal_truth(signals: dict, name: str) -> bool:
    value = signals.get(name)
    if isinstance(value, bool):
        return value
    try:
        return float(value or 0.0) >= 0.6
    except (TypeError, ValueError):
        return False


def _model_confirmation(primary: EntryModelScore, signals: dict) -> tuple[bool, list[str]]:
    groups = MODEL_CONFIRMATIONS.get(primary.key, ())
    if not groups:
        return primary.eligible, []
    missing: list[str] = []
    for alternatives in groups:
        if not any(_signal_truth(signals, name) for name in alternatives):
            missing.append(" or ".join(name.replace("_", " ") for name in alternatives))
    return not missing, missing


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

        model_confirmed, model_missing = _model_confirmation(primary, setup.signals)
        common_safety = bool(
            setup.entry_valid
            and setup.signals.get("target_not_blocked")
            and (setup.tp2_r or 0.0) >= 2.0
            and setup.confidence >= settings.setup_confidence_floor
        )
        model_gate = bool(
            primary.eligible
            and primary.score >= settings.entry_model_arm_score
            and model_confirmed
        )
        actionable = bool(common_safety and model_gate)

        if actionable:
            reason = (
                f"{primary.name} ranks first at {primary.score:.1f}% and its model-specific confirmations are complete. "
                f"The engine retained {len(alternatives)} qualified backup model(s)."
            )
        elif primary.eligible:
            waiting = model_missing or [
                f"model score {settings.entry_model_arm_score:.0f}%" if primary.score < settings.entry_model_arm_score else "common risk safety"
            ]
            reason = (
                f"{primary.name} ranks first at {primary.score:.1f}%, but the limit remains unarmed while waiting for: "
                f"{', '.join(waiting)}."
            )
        else:
            reason = (
                f"{primary.name} is currently the strongest developing model at {primary.score:.1f}%, "
                f"but it is missing: {', '.join(primary.missing) or 'mandatory confirmation'}."
            )

        status = "WAITING_FOR_LIMIT" if actionable else "DEVELOPING" if (
            primary.eligible and primary.score >= settings.setup_watch_model_score and setup.entry_valid
        ) else "SCANNING"
        order_state = "ARMED" if actionable else "PREVIEW_ONLY"

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
                "entry_model_confirmed": model_confirmed,
                "entry_model_missing": model_missing,
                "common_safety_gate": common_safety,
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
