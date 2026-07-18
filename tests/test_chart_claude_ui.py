from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")


def test_chart_page_uses_requested_tradeiq_toolbar():
    for marker in [
        'class="tradeiq-chart-bar"',
        'class="chart-brand-title">Trade<span>IQ</span> · NQ',
        'data-tf="1"',
        'data-tf="3"',
        'data-tf="5"',
        'data-tf="15"',
        'data-tf="60"',
        'data-overlay="emas"',
        'data-overlay="gex"',
        'data-overlay="fib"',
        'data-overlay="zones"',
        'data-overlay="trade"',
        'data-overlay="vwap"',
    ]:
        assert marker in HTML


def test_chart_side_rail_contains_trade_setup_and_claude():
    for marker in [
        'id="chartSideRail"',
        'id="chartSetupPanel"',
        'id="claudePanel"',
        'id="claudeAnalyze"',
        'id="claudeAuto"',
        'id="claudeAnalysis"',
    ]:
        assert marker in HTML
    assert ".tv-full-panel:fullscreen .tv-chart-rail{display:none}" in CSS


def test_frontend_streams_claude_without_mutating_engine():
    for marker in [
        "function startClaudeAnalysis",
        'new EventSource(`/api/ai/analysis/stream',
        'source.addEventListener("delta"',
        'source.addEventListener("done"',
        "read-only analysis",
    ]:
        assert marker in APP
    assert "setup.confidence =" not in APP
