from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")


def test_classic_dashboard_layout_is_present():
    required = [
        'id="page-dashboard"',
        'class="workspace"',
        'id="chart"',
        'id="gexTable"',
        'id="cfBreak"',
        'id="keyCf"',
        'id="setupLabel"',
        'id="gexRegime"',
        'id="sdTable"',
        'id="fibTable"',
    ]
    for marker in required:
        assert marker in HTML


def test_all_sidebar_pages_are_functional_targets():
    for page in ["dashboard", "chart", "gex", "confluence", "setups", "alerts", "positions", "backtest", "settings"]:
        assert f'data-page="{page}"' in HTML
        assert f'id="page-{page}"' in HTML
    assert 'querySelectorAll("#nav button[data-page]")' in JS
