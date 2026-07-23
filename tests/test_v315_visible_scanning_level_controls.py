from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SW = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")


def test_full_levels_are_default_and_clean_is_optional():
    assert "clean: false" in APP
    assert 'scan: true' in APP
    assert 'map: true' in APP
    assert 'data-overlay="clean" title="Compact the active overlays"' in INDEX
    assert 'data-overlay="scan"' in INDEX
    assert 'data-overlay="map"' in INDEX


def test_overlay_choices_persist_and_reset_to_full_level_layout():
    assert 'tradeiq-chart-overlays' in APP
    assert 'saveOverlayPreferences();' in APP
    assert 'state.overlays = { ...DEFAULT_OVERLAYS };' in APP
    assert 'syncOverlayButtons();' in APP


def test_live_scan_is_visible_but_does_not_publish_entry_prices():
    assert 'LIVE SCAN — NO ORDER' in APP
    assert 'Entry (publishes when valid)' in APP
    assert '$("setupEntry").textContent = lockedPlan ? fmt(setup.entry) : "—";' in APP
    assert '$("chartSetupEntry").textContent = lockedPlan ? fmt(setup.entry) : "—";' in APP
    assert '`${scanState} ${setup.direction} · ${scanModel} · NO ORDER`' in CHART


def test_all_enabled_raw_levels_render_when_clean_is_off():
    assert '(setup.gex.levels || []).forEach((level) =>' in CHART
    assert ': (setup.zones || []);' in CHART
    assert 'if (marketMapVisible) renderCleanMarketMapLines(instance, setup);' in CHART
    assert 'const marketMapVisible = overlays.map && setup.market_map;' in CHART


def test_scanning_panel_keeps_models_rankings_and_cluster_visible():
    assert 'const visibleScan = hasVisibleScan(setup);' in APP
    assert 'setup.primary_entry_model ? `${setup.primary_entry_model}' in APP
    assert 'renderModelRanking(setup, "chartModelRanking")' in APP
    assert '$("chartSetupCluster").textContent = clusterDisplay(setup);' in APP


def test_v315_version_and_assets_are_exposed():
    assert '3.1.5-visible-scanning-level-controls' in MAIN
    assert 'tradeiq-v3.1.5-visible-scanning-level-controls-shell' in SW
    assert '?v=315' in INDEX
