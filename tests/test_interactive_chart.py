from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")


def test_lightweight_chart_workstation_is_wired():
    assert "lightweight-charts@5.2.0" in HTML
    assert 'id="chart" class="tv-chart-host"' in HTML
    assert 'id="chartLarge" class="tv-chart-host"' in HTML
    assert 'data-chart-action="recenter"' in HTML
    assert 'data-chart-action="fullscreen"' in HTML
    assert 'data-draw-mode="hline"' in HTML
    assert "Powered by TradingView Lightweight Charts" in HTML


def test_chart_supports_native_interactions_and_overlays():
    for marker in [
        "handleScroll",
        "handleScale",
        "scrollToRealTime",
        "setVisibleLogicalRange",
        "createPriceLine",
        "CandlestickSeries",
        "LineSeries",
        "gex.call_wall",
        "fib_levels",
        "setup.zones",
        "setup.take_profit_2",
    ]:
        assert marker in JS
    assert "TradeIQChartManager" in APP
