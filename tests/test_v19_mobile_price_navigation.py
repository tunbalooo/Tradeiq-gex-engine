from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART_JS = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_mobile_canvas_supports_two_axis_navigation_and_price_scale_zoom():
    assert 'instance.dragMode = p.x >= canvas.clientWidth - 64 ? "price-scale" : "pan"' in CHART_JS
    assert "instance.pricePan = instance.dragPricePan + dy * pricePerPixel" in CHART_JS
    assert "instance.priceZoom = clamp(instance.dragPriceZoom * Math.exp(-dy / 145)" in CHART_JS
    assert 'canvas.addEventListener("dblclick"' in CHART_JS
    assert "resetFallbackPriceScale" in CHART_JS
    assert "touch-action:none" in STYLES


def test_sparse_live_ticks_do_not_replace_full_chart_history():
    assert "fallbackHistoryCache" in CHART_JS
    assert "desktopHistoryCache" in CHART_JS
    assert "MIN_SAFE_HISTORY_BARS = 20" in CHART_JS
    assert "mergeFallbackCandles(seed, incoming)" in CHART_JS
    assert "mergeDesktopCandles(seed, incoming)" in CHART_JS
    assert "HISTORY RESTORED" in CHART_JS


def test_invalid_ohlc_bars_are_rejected_before_chart_rendering():
    assert "high < low || high < Math.max(open, close) || low > Math.min(open, close)" in CHART_JS
    assert "item.high < item.low || item.high < Math.max(item.open, item.close)" in CHART_JS


def test_v19_cache_busts_the_installed_mobile_app():
    assert "tradeiq-v1.9-shell" in SW
    assert "?v=19" in SW
    assert '/static/boot.js?v=19' in INDEX
