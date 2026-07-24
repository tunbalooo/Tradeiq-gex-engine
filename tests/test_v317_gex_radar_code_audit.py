from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from engine.gex import (
    OptionPosition,
    derive_gex_summary_from_positions,
    expiry_breakdown,
    filter_positions_by_expiry,
)

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
CHART = (ROOT / "frontend" / "trading_chart.js").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


def _position(strike: float, option_type: str, oi: int, iv: float, expiration: datetime) -> OptionPosition:
    return OptionPosition(
        strike=strike,
        expiry_years=max((expiration - datetime(2026, 7, 23, 14, tzinfo=timezone.utc)).total_seconds() / (365 * 86400), 1 / 3650),
        option_type=option_type,
        open_interest=oi,
        implied_volatility=iv,
        expiration_ns=int(expiration.timestamp() * 1_000_000_000),
    )


def test_expiry_filters_are_deterministic_and_non_overlapping():
    now = datetime(2026, 7, 23, 14, tzinfo=timezone.utc)
    positions = [
        _position(25000, "CALL", 1000, .20, now + timedelta(hours=6)),
        _position(24950, "PUT", 900, .22, now + timedelta(days=3)),
        _position(25100, "CALL", 800, .21, now + timedelta(days=15)),
    ]
    counts = expiry_breakdown(positions, now=now)
    assert counts == {"0DTE": 1, "WEEKLY": 2, "ALL": 3}
    assert len(filter_positions_by_expiry(positions, "0DTE", now=now)) == 1
    assert len(filter_positions_by_expiry(positions, "WEEKLY", now=now)) == 2
    assert len(filter_positions_by_expiry(positions, "ALL", now=now)) == 3


def test_gex_radar_summary_contains_oi_iv_and_intensity_zones():
    now = datetime(2026, 7, 23, 14, tzinfo=timezone.utc)
    expiry = now + timedelta(days=2)
    positions = [
        _position(24900, "PUT", 3500, .24, expiry),
        _position(24950, "PUT", 5200, .23, expiry),
        _position(25000, "CALL", 4600, .20, expiry),
        _position(25050, "CALL", 6100, .19, expiry),
        _position(25100, "CALL", 4200, .20, expiry),
    ]
    summary = derive_gex_summary_from_positions(
        25000,
        positions,
        expiry_filter="WEEKLY",
        available_expiry_filters=["WEEKLY", "ALL"],
        expiry_counts={"0DTE": 0, "WEEKLY": 5, "ALL": 5},
    )
    assert summary["expiry_filter"] == "WEEKLY"
    assert summary["reference_price"] == 25000
    assert summary["available_expiry_filters"] == ["WEEKLY", "ALL"]
    assert summary["intensity_zones"]
    row = next(item for item in summary["by_strike"] if item["strike"] == 25050)
    assert row["call_oi"] == 6100
    assert row["total_oi"] == 6100
    assert row["weighted_iv"] == .19
    assert row["expiration_count"] == 1


def test_frontend_contains_full_gex_radar_and_expiry_controls():
    assert 'data-gex-expiry="0DTE"' in INDEX
    assert 'data-gex-expiry="WEEKLY"' in INDEX
    assert 'data-gex-expiry="ALL"' in INDEX
    assert "GEX Radar by Strike" in INDEX
    assert "Top Gamma Nodes" in INDEX
    assert "GEX Intensity Zones" in INDEX
    assert "/api/gex/summary?expiry=" in APP
    assert "total_oi" in APP
    assert "weighted_iv" in APP
    assert "intensity_zones" in CHART
    assert "3.1.7-gex-radar-code-audit" in MAIN


def test_gex_summary_endpoint_accepts_expiry_filter():
    with TestClient(app) as client:
        response = client.get("/api/gex/summary?expiry=ALL")
        invalid = client.get("/api/gex/summary?expiry=MONTHLY")
    assert response.status_code == 200
    assert response.json()["expiry_filter"] == "ALL"
    assert invalid.status_code == 422
