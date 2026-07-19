from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from engine.gex import OptionPosition, derive_gex_summary_from_positions

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART_JS = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def test_gex_summary_exposes_complete_by_strike_profile():
    positions = [
        OptionPosition(7400, 7 / 365, "PUT", 1500, 0.20, contract_multiplier=50),
        OptionPosition(7450, 7 / 365, "PUT", 1200, 0.20, contract_multiplier=50),
        OptionPosition(7500, 7 / 365, "CALL", 1800, 0.20, contract_multiplier=50),
        OptionPosition(7550, 7 / 365, "CALL", 1100, 0.20, contract_multiplier=50),
    ]
    result = derive_gex_summary_from_positions(7495, positions)
    assert [row["strike"] for row in result["by_strike"]] == [7400.0, 7450.0, 7500.0, 7550.0]
    assert result["by_strike"][0]["put_gex"] < 0
    assert result["by_strike"][-1]["call_gex"] > 0
    assert all("net_gex" in row for row in result["by_strike"])


def test_dashboard_api_includes_gex_by_strike_for_desktop_and_mobile():
    with TestClient(app) as client:
        payload = client.get("/api/dashboard").json()
    rows = payload["setup"]["gex"]["by_strike"]
    assert len(rows) >= 3
    assert {"strike", "call_gex", "put_gex", "net_gex"}.issubset(rows[0])


def test_desktop_gex_page_has_exposure_by_strike_canvas():
    assert 'id="gexStrikeChart"' in INDEX
    assert 'id="gexStrikeSource"' in INDEX
    assert "function drawGexStrikeChart" in APP_JS
    assert "gex.by_strike" in APP_JS
    assert ".gex-strike-panel" in STYLES


def test_mobile_uses_native_canvas_manager_instead_of_blank_hidden_chart():
    assert "USE_MOBILE_CANVAS" in CHART_JS
    assert 'matchMedia?.("(max-width: 900px)")' in CHART_JS
    assert "installCanvasFallback();" in CHART_JS
    assert "bindFallbackGestures" in CHART_JS
    assert "mobileCanvas: USE_MOBILE_CANVAS" in CHART_JS
    assert ".tradeiq-canvas-fallback" in STYLES
    assert "touch-action:none" in STYLES


def test_mobile_news_is_split_into_standard_calendar_and_headline_tabs():
    assert 'data-mobile-news-tab="calendar"' in INDEX
    assert 'data-mobile-news-tab="headlines"' in INDEX
    assert 'id="mobileCalendarPane"' in INDEX
    assert 'id="mobileHeadlinesPane"' in INDEX
    assert "function setMobileNewsTab" in APP_JS
    assert "economic-day-group" in APP_JS
    assert "headline-row" in APP_JS


def test_v18_shell_cache_busts_old_installed_mobile_ui():
    assert "tradeiq-v1.8-shell" in SW
    assert "?v=18" in SW
    assert '/static/boot.js?v=18' in INDEX
