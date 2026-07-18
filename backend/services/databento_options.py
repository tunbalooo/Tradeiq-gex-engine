"""
Databento options — native CME NQ options-on-futures chain for TRUE NQ GEX.

Returns OptionPosition[] (strike, expiry_years, CALL/PUT, open_interest,
implied_volatility) exactly like live_options.py, so engine/gex.py (Black-76)
runs unchanged. No QQQ proxy, no rescaling — these are real NQ contracts.

Pipeline (all from GLBX.MDP3):
  - definitions  -> strike, expiration, call/put, instrument_id
  - statistics   -> open interest  (stat_type 9)
  - trades/tob   -> last price to solve implied volatility if not supplied

This is heavier than yfinance and licensed for local personal use. It's built
defensively: any failure returns [] so setup_service falls back to the proxy
for that cycle rather than crashing.

Because a full definitions+stats+IV solve is a real project, this first version
fetches definitions + open interest and derives a conservative IV surface from
distance-to-money (same shape the engine already tolerates). A follow-up can
replace the IV estimate with solved IV from option trade prices.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from backend.core.config import settings
from engine.gex import OptionPosition

logger = logging.getLogger("tradeiq.databento_options")

try:
    import databento as db
except ImportError:  # pragma: no cover
    db = None

_cache: dict = {"positions": [], "ts": 0.0}
_REFRESH = 60  # option OI is a daily stat; refreshing each minute is plenty

STAT_TYPE_OPEN_INTEREST = 9


def _estimate_iv(strike: float, underlying: float) -> float:
    # Conservative smile until we solve IV from option trades: ATM ~0.18,
    # rising with absolute moneyness. Keeps gamma sane for wall detection.
    if underlying <= 0:
        return 0.2
    moneyness = abs(strike - underlying) / underlying
    return round(0.18 + moneyness * 2.2, 4)


def _fetch(underlying_price: float) -> list[OptionPosition]:
    client = db.Historical(settings.databento_api_key)
    now = datetime.now(timezone.utc)

    # 1) Option definitions for the NQ options parent (strikes/expiries/type).
    defs = client.timeseries.get_range(
        dataset=settings.databento_dataset,
        schema="definition",
        stype_in="parent",
        symbols=[settings.databento_options_parent],
        start=now.date().isoformat(),
    ).to_df()
    if defs is None or defs.empty:
        return []

    # 2) Open interest from the statistics schema (stat_type 9).
    oi_by_instrument: dict[int, int] = {}
    try:
        stats = client.timeseries.get_range(
            dataset=settings.databento_dataset,
            schema="statistics",
            stype_in="parent",
            symbols=[settings.databento_options_parent],
            start=now.date().isoformat(),
        ).to_df()
        for _, row in stats.iterrows():
            if int(row.get("stat_type", -1)) == STAT_TYPE_OPEN_INTEREST:
                oi_by_instrument[int(row["instrument_id"])] = int(row.get("quantity", 0) or 0)
    except Exception as exc:
        logger.warning("Databento statistics (OI) fetch failed: %s", exc)

    positions: list[OptionPosition] = []
    for _, d in defs.iterrows():
        try:
            cp = str(d.get("instrument_class", "")).upper()  # 'C' / 'P'
            if cp not in ("C", "P"):
                continue
            strike = float(d["strike_price"]) * 1e-9  # fixed-point -> price
            exp_raw = d.get("expiration")
            exp_dt = exp_raw.to_pydatetime() if hasattr(exp_raw, "to_pydatetime") else now
            years = max((exp_dt - now).days, 1) / 365.0
            oi = oi_by_instrument.get(int(d["instrument_id"]), 0)
            if oi <= 0:
                continue
            positions.append(OptionPosition(
                strike=round(strike, 2),
                expiry_years=years,
                option_type="CALL" if cp == "C" else "PUT",
                open_interest=oi,
                implied_volatility=_estimate_iv(strike, underlying_price),
            ))
        except Exception:
            continue

    return positions


def databento_option_chain(underlying_price: float) -> list[OptionPosition]:
    """Native NQ option positions for the Black-76 engine. Cached, empty-safe."""
    if db is None or not settings.databento_api_key:
        return []
    now = time.time()
    if _cache["positions"] and now - _cache["ts"] < _REFRESH:
        return _cache["positions"]
    try:
        positions = _fetch(underlying_price)
        if positions:
            _cache.update(positions=positions, ts=now)
        return positions
    except Exception as exc:
        logger.warning("Databento option chain fetch failed: %s", exc)
        _cache["ts"] = now  # avoid hammering on repeated failure
        return _cache["positions"]
