from pathlib import Path

from backend.services.claude_analysis import SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")


def test_preview_is_explained_as_watch_only_candidate():
    assert "chartPreviewNotice" in HTML
    assert "SCANNING — NO ACTIVE SETUP" in HTML
    assert "previewExplanation" in APP
    assert "not an armed order" in APP


def test_chart_preview_does_not_draw_trade_lines_before_arming():
    assert "hasLockedTradePlan(setup)" in CHART
    assert '"WATCH"' not in CHART


def test_claude_prompt_is_compact_and_honest_about_previews():
    prompt = SYSTEM_PROMPT.lower()
    assert "no more than 130 words" in prompt
    assert "not a forecast, scheduled trade, or guarantee" in prompt
    assert "do not repeat entry, stop, tp1, or tp2" in prompt
    assert "fallback gex is an estimate" in prompt
