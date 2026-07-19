from datetime import timezone
from pathlib import Path

from backend.services.finnhub_news import FinnhubNewsService


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART_JS = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
BOOT_JS = (ROOT / "frontend" / "boot.js").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def test_mobile_chart_boot_is_sequential_and_has_canvas_fallback():
    assert '/static/boot.js?v=19' in INDEX
    assert 'await loadScript("/static/trading_chart.js?v=19")' in BOOT_JS
    assert 'await loadScript("/static/app.js?v=19")' in BOOT_JS
    assert "installCanvasFallback" in CHART_JS
    assert "tradeiq-canvas-fallback" in CHART_JS
    assert "window.TradeIQChartManager" in CHART_JS


def test_mobile_chart_waits_for_visible_size_and_resizes_explicitly():
    assert "hostIsReady" in CHART_JS
    assert "scheduleRender" in CHART_JS
    assert "autoSize: false" in CHART_JS
    assert "instance.chart.resize(width, height)" in CHART_JS
    assert "orientationchange" in APP_JS
    assert "visibilitychange" in APP_JS
    assert "scheduleChartDraw" in APP_JS
    assert ".tv-chart-host{min-width:0;min-height:300px" in STYLES


def test_news_ui_uses_weekday_date_time_and_et_timezone():
    assert "function newsDateParts" in APP_JS
    assert 'weekday: "short"' in APP_JS
    assert 'timeZone: "America/New_York"' in APP_JS
    assert "stamp.date" in APP_JS
    assert "stamp.time" in APP_JS
    assert "news-datetime" in STYLES
    assert ".mobile-news-card time b" in STYLES


def test_finnhub_items_keep_utc_published_at_for_client_formatting():
    service = FinnhubNewsService()
    rows = service._score_news([
        {
            "headline": "Nasdaq and Federal Reserve headline",
            "summary": "Treasury yields move technology shares",
            "datetime": 1_700_000_000,
            "source": "Test",
            "url": "https://example.com/item",
        }
    ], ("nasdaq", "federal reserve", "treasury yields"))
    assert rows[0].published_at is not None
    assert rows[0].published_at.tzinfo == timezone.utc
    assert rows[0].time != "—"


def test_v16_service_worker_updates_installed_mobile_apps():
    assert 'tradeiq-v1.9-shell' in SW
    assert '/static/boot.js?v=19' in SW
    assert "fetch(request).then" in SW
