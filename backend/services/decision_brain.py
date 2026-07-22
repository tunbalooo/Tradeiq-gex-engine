"""Central deterministic coordinator for TradeIQ.

The Decision Brain selects either the strongest single institutional model or a
composite confluence cluster, then delegates *how* to execute to the adaptive
execution selector. Claude remains read-only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.core.config import settings
from backend.models.schemas import EntryModelScore, TradeSetup
from backend.services.instruments import get_instrument
from engine.adaptive_execution import select_execution
from engine.institutional_cluster import build_cluster_score


MODEL_CONFIRMATIONS: dict[str, tuple[tuple[str, ...], ...]] = {
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
    contract = (signals.get("model_confirmations") or {}).get(primary.key)
    if isinstance(contract, dict):
        return bool(contract.get("confirmed")), [str(item) for item in (contract.get("missing") or [])]
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
        single_primary = eligible[0] if eligible else (ranking[0] if ranking else None)
        cluster = build_cluster_score(setup.signals, ranking, setup.cluster_score)

        use_cluster = bool(
            cluster["eligible"]
            and len(eligible) >= 2
            and single_primary is not None
            and cluster["score"] >= max(82.0, single_primary.score + 5.0)
        )
        if use_cluster:
            primary = EntryModelScore(
                key="INSTITUTIONAL_CONFLUENCE_CLUSTER",
                name="Institutional Confluence Cluster",
                direction=setup.direction,
                score=cluster["score"],
                eligible=True,
                priority=0,
                trigger_price=single_primary.trigger_price,
                invalidation_price=single_primary.invalidation_price,
                reason=[f"Independent evidence aligned across {len(cluster['active_categories'])} categories"],
                missing=[],
            )
            alternatives = eligible[:3]
            model_confirmed = any(
                _model_confirmation(item, setup.signals)[0]
                for item in eligible[:4]
            ) and _signal_truth(setup.signals, "displacement")
            model_missing = [] if model_confirmed else ["confirmed rejection, displacement, or structure shift from the stacked cluster"]
        else:
            primary = single_primary
            alternatives = eligible[1:4] if eligible else []
            if primary is None:
                return setup.model_copy(update={
                    "primary_entry_model": None,
                    "entry_model_scores": ranking,
                    "alternative_entry_models": [],
                    "model_selection_reason": "No entry model produced sufficient deterministic evidence.",
                    "actionable": False,
                    "execution_type": "NONE",
                })
            model_confirmed, model_missing = _model_confirmation(primary, setup.signals)

        common_safety = bool(
            setup.signals.get("target_not_blocked")
            and (setup.tp2_r or 0.0) >= 2.0
            and setup.confidence >= settings.setup_confidence_floor
        )
        model_gate = bool(primary.eligible and primary.score >= settings.entry_model_arm_score and model_confirmed)

        profile = get_instrument(setup.symbol)
        current_price = float(setup.signals.get("current_price") or setup.entry or 0.0)
        if setup.entry and abs(current_price - float(setup.entry)) / max(abs(float(setup.entry)), 1e-9) > 0.08:
            # Persisted/tests may replace trade levels without replacing the source
            # market snapshot. Never let a stale price regime decide execution.
            current_price = float(setup.entry)
        execution = select_execution(
            model_key=primary.key,
            direction=setup.direction,
            current_price=current_price,
            ideal_entry=setup.entry,
            atr=setup.atr,
            tick_size=profile.tick_size,
            model_confirmed=model_gate,
            entry_valid=setup.entry_valid,
            target_not_blocked=bool(setup.signals.get("target_not_blocked")),
            tp1=setup.take_profit_1,
            tp2=setup.take_profit_2,
            tp2_r=setup.tp2_r,
            composite_score=cluster["score"],
        )
        actionable = bool(common_safety and model_gate and execution.executable)

        if actionable:
            reason = (
                f"{primary.name} ranks first at {primary.score:.1f}%. "
                f"Adaptive execution selected {execution.execution_type}: {execution.reason}"
            )
        elif primary.eligible:
            waiting = model_missing or ["execution freshness or common risk safety"]
            reason = f"{primary.name} ranks first at {primary.score:.1f}%, but execution is waiting for: {', '.join(waiting)}."
        else:
            reason = f"{primary.name} is the strongest developing model at {primary.score:.1f}%, but is missing: {', '.join(primary.missing) or 'mandatory confirmation'}."

        status = "EXECUTION_READY" if actionable else "DEVELOPING" if (
            primary.eligible and primary.score >= settings.setup_watch_model_score
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
            "composite_cluster_score": cluster["score"],
            "composite_cluster_eligible": cluster["eligible"],
            "composite_cluster_categories": cluster["categories"],
            "composite_cluster_contributors": cluster["contributors"],
            "execution_type": execution.execution_type,
            "execution_reason": execution.reason,
            "execution_freshness_score": execution.freshness_score,
            "execution_distance_points": execution.distance_points,
            "execution_selected_at": datetime.now(timezone.utc),
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
                "execution_type": execution.execution_type,
                "execution_fresh": execution.freshness_score >= 30.0,
                "composite_cluster": cluster,
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
            "execution": {
                "type": setup.execution_type,
                "reason": setup.execution_reason,
                "freshness": setup.execution_freshness_score,
                "distance_points": setup.execution_distance_points,
            },
            "cluster": {
                "score": setup.composite_cluster_score,
                "eligible": setup.composite_cluster_eligible,
                "categories": setup.composite_cluster_categories,
                "contributors": setup.composite_cluster_contributors,
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
