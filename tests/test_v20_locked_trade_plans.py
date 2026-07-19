from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
ENGINE = (ROOT / "backend" / "services" / "trade_engine.py").read_text(encoding="utf-8")


def test_trade_lines_and_risk_box_require_a_locked_active_plan():
    assert 'const ACTIVE_TRADE_STATES = new Set(["WAITING_FOR_LIMIT", "FILLED", "TP1_HIT"]);' in CHART
    assert "function hasLockedTradePlan(setup)" in CHART
    assert CHART.count("overlays.trade && hasLockedTradePlan(setup)") == 3
    assert 'setup.order_state === "PREVIEW_ONLY" ? "WATCH" : "ENTRY"' not in CHART


def test_preview_levels_are_hidden_in_setup_panels_until_armed():
    assert "function hasLockedTradePlan(setup)" in APP
    assert '"Entry (locks when armed)"' in APP
    assert 'lockedPlan ? fmt(setup.entry) : "—"' in APP
    assert 'lockedPlan ? fmt(setup.stop_loss) : "—"' in APP
    assert "SCANNING — NO ACTIVE SETUP" in INDEX


def test_armed_trade_levels_remain_immutable_while_context_refreshes():
    refresh_section = ENGINE.split("def _refresh_context", 1)[1].split("def _transition", 1)[0]
    for field in ("entry", "stop_loss", "take_profit_1", "take_profit_2", "risk_reward"):
        assert f'"{field}"' not in refresh_section


def test_v20_cache_and_version_are_visible():
    assert "tradeiq-v2.0-shell" in SW
    assert "?v=20" in SW
    assert "2.0.0-locked-trade-plans" in MAIN
