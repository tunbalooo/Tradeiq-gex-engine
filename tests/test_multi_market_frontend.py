from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")


def test_frontend_has_six_market_selector():
    assert 'id="symbolSelect"' in HTML
    for symbol in ("NQ", "MNQ", "ES", "MES", "GC", "MGC"):
        assert f'<option value="{symbol}">{symbol}</option>' in HTML


def test_frontend_switches_without_hard_coded_nq_chart_labels():
    assert 'fetch("/api/market/symbol"' in APP
    assert "function switchMarket" in APP
    assert "instrumentName()" in APP
    assert "gex.source_label" in APP
    assert "NASDAQ 100 E-mini" not in APP
    assert "NASDAQ 100 E-mini" not in CHART
    assert "instance.displaySymbol" in CHART
    assert "pricePrecision" in CHART
