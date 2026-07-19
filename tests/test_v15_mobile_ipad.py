from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
MANIFEST = (ROOT / "frontend" / "manifest.webmanifest").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def test_mobile_ipad_workspace_is_connected_to_existing_live_ids():
    for token in [
        'id="symbolSelect"',
        'id="chartLarge"',
        'id="chartSetupPanel"',
        'id="claudePanel"',
        'id="mobileNewsList"',
        'id="mobileGexPanel"',
        'id="mobileBottomNav"',
    ]:
        assert token in INDEX
    assert 'fetch("/api/market/symbol"' in APP_JS
    assert "new WebSocket" in APP_JS
    assert "startClaudeAnalysis" in APP_JS


def test_responsive_breakpoints_and_safe_area_are_present():
    assert "@media (max-width:900px)" in STYLES
    assert "@media (max-width:560px)" in STYLES
    assert "env(safe-area-inset-bottom)" in STYLES
    assert ".mobile-bottom-nav" in STYLES
    assert ".tv-chart-rail" in STYLES


def test_pwa_assets_and_root_scope_service_worker_are_configured():
    assert 'rel="manifest"' in INDEX
    assert 'navigator.serviceWorker.register("/service-worker.js", { scope: "/" })' in INDEX
    assert '"display": "standalone"' in MANIFEST
    assert "tradeiq-v1.5-shell" in SW
    assert (ROOT / "frontend" / "app-icon-192.png").exists()
    assert (ROOT / "frontend" / "app-icon-512.png").exists()


def test_service_worker_route_is_available():
    with TestClient(app) as client:
        response = client.get("/service-worker.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers.get("service-worker-allowed") == "/"
