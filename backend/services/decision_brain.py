"""Central deterministic coordinator for TradeIQ.

The Decision Brain compares a strong single institutional model with a composite
confluence cluster, then delegates *how* to execute to the adaptive execution
selector. Claude remains read-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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


def _cluster_confirmation(
    cluster: dict[str, Any],
    eligible: list[EntryModelScore],
    signals: dict[str, Any],
) -> tuple[bool, list[str], int, list[str]]:
    confirmed_models = [
        item.name for item in eligible[:6]
        if _model_confirmation(item, signals)[0]
    ]
    event_names = (
        "displacement",
        "ordered_sequence",
        "liquidity_sweep",
        "fib_pullback_rejection",
        "volume_expansion",
    )
    confirmed_events = [name for name in event_names if _signal_truth(signals, name)]
    # A model-native confirmation counts once; additional price-action events add
    # strength. This prevents a two-factor location from trading on touch alone.
    strength = min(2, len(confirmed_models)) + min(3, len(confirmed_events))
    required = int(cluster.get("required_confirmation_strength") or 1)
    confirmed = bool(confirmed_models and strength >= required)
    missing: list[str] = []
    if not confirmed_models:
        missing.append("at least one model-native rejection, reclaim, or structure confirmation")
    if strength < required:
        missing.append(f"confirmation strength {required} (currently {strength})")
    return confirmed, missing, strength, confirmed_models


class DecisionBrainService:
    def select(self, setup: TradeSetup, ranking: list[EntryModelScore]) -> TradeSetup:
        eligible = [item for item in ranking if item.eligible]
        single_primary = eligible[0] if eligible else (ranking[0] if ranking else None)
        cluster = build_cluster_score(setup.signals, ranking, setup.cluster_score)

        if single_primary is None:
            return setup.model_copy(update={
                "primary_entry_model": None,
                "entry_model_scores": ranking,
                "alternative_entry_models": [],
                "model_selection_reason": "No entry model produced sufficient deterministic evidence.",
                "actionable": False,
                "execution_type": "NONE",
            })

        single_confirmed, single_missing = _model_confirmation(single_primary, setup.signals)
        cluster_primary: EntryModelScore | None = None
        cluster_confirmed = False
        cluster_missing: list[str] = []
        cluster_confirmation_strength = 0
        cluster_confirmed_models: list[str] = []

        if cluster["eligible"] and eligible and len(ranking) >= 2:
            cluster_primary = EntryModelScore(
                key="INSTITUTIONAL_CONFLUENCE_CLUSTER",
                name="Institutional Confluence Cluster",
                direction=setup.direction,
                score=cluster["score"],
                eligible=True,
                priority=0,
                trigger_price=single_primary.trigger_price,
                invalidation_price=single_primary.invalidation_price,
                reason=[
                    f"{cluster['category_count']} independent evidence categories",
                    f"{cluster['tier'].replace('_', ' ').title()} cluster",
                ],
                missing=[],
            )
            (
                cluster_confirmed,
                cluster_missing,
                cluster_confirmation_strength,
                cluster_confirmed_models,
            ) = _cluster_confirmation(cluster, eligible, setup.signals)

        profile = get_instrument(setup.symbol)
        current_price = float(setup.signals.get("current_price") or setup.entry or 0.0)
        if setup.entry and abs(current_price - float(setup.entry)) / max(abs(float(setup.entry)), 1e-9) > 0.08:
            # Persisted/tests may replace trade levels without replacing the source
            # market snapshot. Never let a stale price regime decide execution.
            current_price = float(setup.entry)

        def evaluate(
            primary: EntryModelScore,
            model_confirmed: bool,
            model_missing: list[str],
            *,
            composite: bool,
        ) -> dict[str, Any]:
            minimum_confidence = float(settings.setup_confidence_floor)
            minimum_freshness = 0.0
            cluster_quality_missing: list[str] = []
            if composite:
                minimum_confidence = float(cluster.get("minimum_confidence") or minimum_confidence)
                minimum_freshness = float(cluster.get("minimum_freshness") or 0.0)
                required_strength = int(cluster.get("required_confirmation_strength") or 1)
                if cluster_confirmation_strength < required_strength:
                    cluster_quality_missing.append(
                        f"cluster confirmation strength {required_strength} (currently {cluster_confirmation_strength})"
                    )

            common_safety = bool(
                setup.signals.get("target_not_blocked")
                and (setup.tp2_r or 0.0) >= 2.0
                and setup.confidence >= minimum_confidence
            )
            model_gate = bool(
                primary.eligible
                and primary.score >= settings.entry_model_arm_score
                and model_confirmed
            )
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
                stop_loss=setup.stop_loss,
                source_model_key=single_primary.key if composite else primary.key,
            )
            if composite and execution.freshness_score < minimum_freshness:
                cluster_quality_missing.append(
                    f"execution freshness {minimum_freshness:.0f}% (currently {execution.freshness_score:.0f}%)"
                )
            if setup.confidence < minimum_confidence:
                cluster_quality_missing.append(
                    f"institutional confidence {minimum_confidence:.0f}% (currently {setup.confidence:.0f}%)"
                )
            cluster_quality_gate = not cluster_quality_missing
            actionable = bool(
                common_safety and model_gate and execution.executable and cluster_quality_gate
            )
            return {
                "primary": primary,
                "confirmed": model_confirmed,
                "missing": model_missing,
                "common_safety": common_safety,
                "model_gate": model_gate,
                "execution": execution,
                "cluster_quality_gate": cluster_quality_gate,
                "cluster_quality_missing": cluster_quality_missing,
                "actionable": actionable,
                "composite": composite,
            }

        single_eval = evaluate(single_primary, single_confirmed, single_missing, composite=False)
        cluster_eval = (
            evaluate(cluster_primary, cluster_confirmed, cluster_missing, composite=True)
            if cluster_primary is not None
            else None
        )

        # Compare the cluster's auditable selection score with the strongest valid
        # single model. A cluster is not automatically preferred merely because it
        # has more labels; a strong single model may still remain primary.
        prefer_cluster = bool(
            cluster_eval is not None
            and cluster["selection_score"] >= single_primary.score
        )
        ordered_evaluations = (
            [cluster_eval, single_eval]
            if prefer_cluster and cluster_eval is not None
            else [single_eval] + ([cluster_eval] if cluster_eval is not None else [])
        )
        selected = next((item for item in ordered_evaluations if item and item["actionable"]), None)
        if selected is None:
            selected = ordered_evaluations[0]

        primary = selected["primary"]
        model_confirmed = selected["confirmed"]
        model_missing = selected["missing"]
        execution = selected["execution"]
        actionable = selected["actionable"]
        using_cluster = selected["composite"]

        if using_cluster:
            alternatives = eligible[:3]
        else:
            alternatives = eligible[1:4] if eligible else []
            if cluster_primary is not None:
                alternatives = [cluster_primary] + alternatives

        if actionable:
            reason = (
                f"{primary.name} ranks first at {primary.score:.1f}%. "
                f"Adaptive execution selected {execution.execution_type}: {execution.reason}"
            )
            if not using_cluster and cluster_eval is not None and prefer_cluster and not cluster_eval["actionable"]:
                reason += " The composite cluster was recognized, but its stricter tier quality gate was incomplete, so the valid single model was used."
        elif primary.eligible:
            waiting = model_missing + selected["cluster_quality_missing"]
            if not selected["common_safety"]:
                waiting.append("target path, minimum 2R, or confidence safety")
            if not execution.executable:
                waiting.append("fresh executable price")
            waiting = list(dict.fromkeys(waiting or ["execution freshness or common risk safety"]))
            reason = (
                f"{primary.name} ranks first at {primary.score:.1f}%, but execution is waiting for: "
                f"{', '.join(waiting)}."
            )
        else:
            reason = (
                f"{primary.name} is the strongest developing model at {primary.score:.1f}%, "
                f"but is missing: {', '.join(primary.missing) or 'mandatory confirmation'}."
            )

        status = "EXECUTION_READY" if actionable else "DEVELOPING" if (
            primary.eligible and primary.score >= settings.setup_watch_model_score
        ) else "SCANNING"
        order_state = "ARMED" if actionable else "PREVIEW_ONLY"

        return setup.model_copy(update={
            "primary_entry_model": primary.name,
            "primary_entry_model_key": primary.key,
            "primary_model_score": primary.score,
            "entry_model_scores": ranking,
            "alternative_entry_models": [item.name for item in alternatives[:4]],
            "model_selection_reason": reason,
            "model_selected_at": datetime.now(timezone.utc),
            "composite_cluster_score": cluster["score"],
            "composite_cluster_selection_score": cluster["selection_score"],
            "composite_cluster_eligible": cluster["eligible"],
            "composite_cluster_tier": cluster["tier"],
            "composite_cluster_active_categories": cluster["active_categories"],
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
                "entry_model_gate": selected["model_gate"],
                "entry_model_confirmed": model_confirmed,
                "entry_model_missing": model_missing,
                "common_safety_gate": selected["common_safety"],
                "primary_model_key": primary.key,
                "execution_type": execution.execution_type,
                "execution_fresh": execution.freshness_score >= 30.0,
                "composite_cluster": cluster,
                "cluster_confirmation_strength": cluster_confirmation_strength,
                "cluster_confirmed_models": cluster_confirmed_models,
                "cluster_quality_gate": selected["cluster_quality_gate"] if using_cluster else None,
                "cluster_quality_missing": selected["cluster_quality_missing"] if using_cluster else [],
                "selected_as_cluster": using_cluster,
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
                "selection_score": setup.composite_cluster_selection_score,
                "eligible": setup.composite_cluster_eligible,
                "tier": setup.composite_cluster_tier,
                "active_categories": setup.composite_cluster_active_categories,
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
