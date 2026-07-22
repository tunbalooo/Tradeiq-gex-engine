from pathlib import Path

from engine.adaptive_execution import select_execution


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def _decision(**updates):
    values = {
        "model_key": "OTE_RETRACEMENT",
        "direction": "SHORT",
        "current_price": 100.0,
        "ideal_entry": 105.0,
        "atr": 10.0,
        "tick_size": 0.25,
        "model_confirmed": True,
        "entry_valid": True,
        "target_not_blocked": True,
        "tp1": 90.0,
        "tp2": 80.0,
        "tp2_r": 4.0,
        "stop_loss": 110.0,
    }
    values.update(updates)
    return select_execution(**values)


def test_nearby_retracement_level_arms_a_real_limit():
    decision = _decision()
    assert decision.execution_type == "LIMIT"
    assert decision.executable is True
    assert "nearby" in decision.reason.lower()
    assert "liquidity" in decision.reason.lower()


def test_distant_retracement_remains_internal_and_is_not_published_as_limit():
    decision = _decision(ideal_entry=120.0, stop_loss=125.0)
    assert decision.execution_type == "NONE"
    assert decision.executable is False
    assert "too far" in decision.reason.lower()
    assert "internal" in decision.reason.lower()


def test_retracement_confirmation_at_the_level_can_enter_market():
    decision = _decision(ideal_entry=100.5)
    assert decision.execution_type == "MARKET"
    assert decision.executable is True
    assert "retracement confirmed" in decision.reason.lower()


def test_fast_continuation_never_falls_back_to_a_distant_limit():
    decision = _decision(
        model_key="TREND_CONTINUATION",
        ideal_entry=110.0,
        stop_loss=105.0,
    )
    assert decision.execution_type == "NONE"
    assert "distant limit" in decision.reason.lower()


def test_limit_is_rejected_when_opposing_liquidity_is_too_close():
    decision = _decision(current_price=100.0, ideal_entry=101.5, tp1=97.5, stop_loss=106.5)
    assert decision.execution_type == "NONE"
    assert "opposing liquidity" in decision.reason.lower()


def test_cluster_uses_the_underlying_model_execution_family():
    retracement_cluster = _decision(
        model_key="INSTITUTIONAL_CONFLUENCE_CLUSTER",
        source_model_key="OTE_RETRACEMENT",
    )
    continuation_cluster = _decision(
        model_key="INSTITUTIONAL_CONFLUENCE_CLUSTER",
        source_model_key="LIQUIDITY_SWEEP_MSS",
        ideal_entry=100.5,
    )
    assert retracement_cluster.execution_type == "LIMIT"
    assert continuation_cluster.execution_type == "MARKET"


def test_watch_prices_are_not_rendered_on_chart_or_setup_panel():
    assert "addPriceLine(instance, watchTrigger(setup)" not in CHART
    assert "horizontal(ctx, toY(watchTrigger(setup))" not in CHART
    assert '$("setupEntry").textContent = lockedPlan ? fmt(setup.entry) : "—";' in APP
    assert '$("chartSetupEntry").textContent = lockedPlan ? fmt(setup.entry) : "—";' in APP
    assert "SCANNING QUIETLY — NO ACTIONABLE ENTRY" in APP
    assert "rankings publish with a validated entry" in APP


def test_claude_auto_analysis_is_silent_until_entry_is_published():
    assert "function claudePublishableSetup(setup)" in APP
    assert "!claudePublishableSetup(state.setup)" in APP
    assert "!claudePublishableSetup(previousSetup) && !claudePublishableSetup(nextSetup)" in APP


def test_v312_version_and_cache_are_exposed():
    assert "3.1.2-silent-real-entry-routing" in MAIN
    assert "tradeiq-v3.1.2-silent-real-entry-routing-shell" in SW
    assert "?v=312" in SW
