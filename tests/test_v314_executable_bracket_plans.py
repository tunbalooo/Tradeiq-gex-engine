from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
BOOT = (ROOT / "frontend" / "boot.js").read_text(encoding="utf-8")


def test_exact_buy_sell_execution_labels_are_rendered():
    assert "function executionOrderLabel(setup, includeState = false)" in CHART
    assert 'const side = setup.direction === "SHORT" ? "SELL" : "BUY";' in CHART
    assert 'let label = `${side} ${type}`;' in CHART
    assert "executionOrderLabel(setup, true)" in CHART
    assert "function executionOrderName(setup)" in APP
    assert 'return ["MARKET", "LIMIT", "STOP"].includes(type) ? `${side} ${type}` : "NO ENTRY";' in APP


def test_chart_draws_a_real_green_reward_and_red_risk_bracket():
    assert 'ctx.fillStyle = "rgba(38,208,124,.13)";' in CHART
    assert 'ctx.fillStyle = "rgba(255,77,94,.14)";' in CHART
    assert "const rewardTop = Math.min(entry, tp2);" in CHART
    assert "const riskTop = Math.min(entry, stop);" in CHART
    assert "ctx.moveTo(startX, tp1); ctx.lineTo(endX, tp1);" in CHART
    assert "tradePlanStartX(instance, chartWidth)" in CHART
    assert "TP2 ${formatPrice(setup.take_profit_2, precision)}" in CHART
    assert "SL ${formatPrice(initialStop(setup), precision)}" in CHART


def test_bracket_is_only_published_for_a_locked_executable_plan():
    assert 'const ACTIVE_TRADE_STATES = new Set(["WAITING_FOR_LIMIT", "FILLED", "TP1_HIT"]);' in CHART
    assert "if (overlays.trade && hasLockedTradePlan(setup))" in CHART
    assert "setup.order_state === \"WATCHING\"" in CHART
    assert "MONITOR ${setup.direction} · NO ORDER" in CHART  # regression marker is comment-only
    assert "addPriceLine(instance, watchTrigger(setup)" not in CHART


def test_panel_publishes_order_action_instead_of_generic_entry_wording():
    assert '$("entryLabel").textContent = lockedPlan ? (setup.order_state === "WAITING_FOR_LIMIT" ? `${executionOrderName(setup)} Armed`' in APP
    assert '$("chartEntryLabel").textContent = lockedPlan ? (setup.order_state === "WAITING_FOR_LIMIT" ? `${executionOrderName(setup)} Armed`' in APP
    assert 'const label = lockedPlan ? `${executionOrderName(setup)} · ${setup.order_state.replaceAll("_", " ")}`' in APP


def test_v314_version_cache_and_asset_bust_are_exposed():
    assert "3.1.4-executable-bracket-plans" in MAIN
    assert "tradeiq-v3.1.4-executable-bracket-plans-shell" in SW
    assert "?v=314" in SW
    assert "?v=314" in INDEX
    assert "?v=314" in BOOT
