from backend.models.schemas import EntryModelScore
from backend.services.decision_brain import decision_brain_service
from backend.services.setup_service import build_candidate_setup
from engine.institutional_cluster import build_cluster_score


def _model(key: str, name: str, score: float, direction: str = "SHORT") -> EntryModelScore:
    return EntryModelScore(
        key=key,
        name=name,
        direction=direction,
        score=score,
        eligible=True,
        trigger_price=100.0,
        invalidation_price=105.0 if direction == "SHORT" else 95.0,
    )


def _two_factor_candidate(confidence: float = 82.0, strongest_score: float = 80.0):
    setup = build_candidate_setup()
    ranking = [
        _model("SUPPLY_DEMAND_RETEST", "Supply/Demand Retest", strongest_score),
        _model("GAMMA_FLIP_RECLAIM", "Gamma Flip Reclaim", 74.0),
    ]
    signals = {
        "current_price": 100.25,
        "target_not_blocked": True,
        "gex_alignment": True,
        "gex_inside_cluster": True,
        "supply_demand": True,
        "gex_ote_zone_cluster": True,
        "model_confirmations": {
            "SUPPLY_DEMAND_RETEST": {
                "confirmed": True,
                "missing": [],
            },
            "GAMMA_FLIP_RECLAIM": {
                "confirmed": True,
                "missing": [],
            },
        },
    }
    candidate = setup.model_copy(update={
        "direction": "SHORT",
        "confidence": confidence,
        "entry_valid": True,
        "entry": 100.0,
        "stop_loss": 105.0,
        "take_profit_1": 90.0,
        "take_profit_2": 80.0,
        "tp1_r": 2.0,
        "tp2_r": 4.0,
        "risk_reward": 4.0,
        "atr": 10.0,
        "cluster_score": 0.9,
        "signals": signals,
    })
    return candidate, ranking


def test_exceptional_two_factor_cluster_can_qualify():
    ranking = [_model("SUPPLY_DEMAND_RETEST", "Supply/Demand Retest", 80.0)]
    cluster = build_cluster_score(
        {"gex_alignment": True, "supply_demand": True},
        ranking,
        0.9,
    )
    assert cluster["eligible"] is True
    assert cluster["tier"] == "EXCEPTIONAL_2_FACTOR"
    assert cluster["category_count"] == 2
    assert cluster["required_confirmation_strength"] == 2
    assert cluster["minimum_freshness"] == 70.0


def test_two_related_labels_still_count_as_one_category():
    ranking = [_model("OTE_RETRACEMENT", "OTE Retracement", 82.0)]
    cluster = build_cluster_score(
        {"ote_overlap": True, "fib_pullback_touched": True},
        ranking,
        1.0,
    )
    assert cluster["eligible"] is False
    assert cluster["category_count"] == 1


def test_weak_two_factor_cluster_is_rejected():
    ranking = [_model("SUPPLY_DEMAND_RETEST", "Supply/Demand Retest", 80.0)]
    cluster = build_cluster_score(
        {"gex_alignment": 0.65, "supply_demand": 0.65},
        ranking,
        0.2,
    )
    assert cluster["eligible"] is False
    assert cluster["score"] < cluster["minimum_score"]


def test_three_and_four_factor_clusters_receive_progressive_tiers():
    ranking = [_model("SUPPLY_DEMAND_RETEST", "Supply/Demand Retest", 80.0)]
    three = build_cluster_score(
        {"gex_alignment": True, "supply_demand": True, "ote_overlap": True},
        ranking,
        0.9,
    )
    four = build_cluster_score(
        {
            "gex_alignment": True,
            "supply_demand": True,
            "ote_overlap": True,
            "liquidity_sweep": True,
        },
        ranking,
        0.9,
    )
    assert three["tier"] == "STANDARD_3_FACTOR"
    assert four["tier"] == "HIGH_PRIORITY_4_PLUS"
    assert four["selection_score"] > three["selection_score"]


def test_decision_brain_can_select_and_execute_exceptional_two_factor_cluster():
    candidate, ranking = _two_factor_candidate()
    selected = decision_brain_service.select(candidate, ranking)
    assert selected.primary_entry_model_key == "INSTITUTIONAL_CONFLUENCE_CLUSTER"
    assert selected.composite_cluster_tier == "EXCEPTIONAL_2_FACTOR"
    assert selected.composite_cluster_active_categories == ["gex", "zone"]
    assert selected.signals["cluster_confirmation_strength"] >= 2
    assert selected.actionable is True
    assert selected.execution_type == "MARKET"


def test_valid_single_model_is_used_when_two_factor_cluster_quality_gate_is_incomplete():
    candidate, ranking = _two_factor_candidate(confidence=70.0)
    selected = decision_brain_service.select(candidate, ranking)
    assert selected.composite_cluster_eligible is True
    assert selected.primary_entry_model_key == "SUPPLY_DEMAND_RETEST"
    assert selected.actionable is True
    assert "single model" in selected.model_selection_reason.lower()


def test_stronger_single_model_can_outrank_an_eligible_cluster():
    candidate, ranking = _two_factor_candidate(strongest_score=95.0)
    selected = decision_brain_service.select(candidate, ranking)
    assert selected.composite_cluster_eligible is True
    assert selected.primary_entry_model_key == "SUPPLY_DEMAND_RETEST"
    assert selected.actionable is True


def test_v311_version_and_cluster_tier_ui_are_exposed():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    main = (root / "backend" / "main.py").read_text(encoding="utf-8")
    app = (root / "frontend" / "app.js").read_text(encoding="utf-8")
    worker = (root / "frontend" / "service-worker.js").read_text(encoding="utf-8")

    assert "3.1.1-flexible-cluster-tiers" in main
    assert "EXCEPTIONAL 2-FACTOR CLUSTER" in app
    assert "STANDARD 3-FACTOR CLUSTER" in app
    assert "HIGH-PRIORITY" in app
    assert "tradeiq-v3.1.1-flexible-cluster-tiers-shell" in worker
