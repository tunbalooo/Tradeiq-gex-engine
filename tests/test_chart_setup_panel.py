from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_full_chart_contains_live_setup_panel():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'class="tv-chart-layout"' in html
    assert 'id="chartSetupPanel"' in html
    assert 'id="chartConfidencePct"' in html
    assert 'id="chartSetupEntry"' in html
    assert 'id="chartSetupValid"' in html


def test_fullscreen_hides_only_chart_setup_panel():
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    assert ".tv-full-panel:fullscreen .tv-chart-setup{display:none}" in css
    assert ".tv-full-panel:fullscreen .tv-chart-layout{grid-template-columns:1fr" in css


def test_chart_setup_is_mirrored_by_frontend_engine():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "function renderChartTradeSetup" in js
    assert '$("chartSetupEntry").textContent = lockedPlan ? fmt(setup.entry) : "—";' in js
    assert '$("chartSetupStatus").textContent = statusText;' in js
    assert '$("chartSetupValid").textContent' in js
