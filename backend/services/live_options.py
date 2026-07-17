"""
Live options chain adapter — fetches a real, free options chain and scales
it onto NQ price so the existing engine/gex.py (Black-76) can compute real
gamma exposure instead of the synthetic mock_option_chain().

Why QQQ and not "real NQ options": true NQ gamma comes from options *on the
Nasdaq futures contract itself*, which is CME data and is paid (Databento,
CME direct, etc — see README). QQQ (the Nasdaq-100 ETF) is the free, liquid
proxy: same underlying index, different price scale. We fetch the real QQQ
chain (strikes, open interest, implied volatility) and rescale every strike
by the live QQQ→NQ price ratio, which preserves moneyness — the thing that
actually matters for gamma. Treat the resulting walls/flip as a proxy signal,
not exact CME dealer positioning.

To upgrade to true NQ options-on-futures gamma later: write a new adapter
with the same live_option_chain(price) -> list[OptionPosition] signature,
backed by Databento/CME, and swap the import in setup_service.py. Nothing
else needs to change.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from backend.core.config import settings
from engine.gex import OptionPosition

logger = logging.getLogger("tradeiq.live_options")

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

_cache: dict = {"positions": [], "ratio": 1.0, "fetched_at": 0.0}


def _fetch_chain(max_expiries: int = 3) -> tuple[list[OptionPosition], float]:
    """Pull the real QQQ chain and return (positions scaled to NQ, qqq spot)."""
    ticker = yf.Ticker(settings.live_options_symbol)  # "QQQ"
    hist = ticker.history(period="1d")
    if hist is None or hist.empty:
        raise RuntimeError("No QQQ spot price returned")
    qqq_spot = float(hist["Close"].iloc[-1])

    expiries = ticker.options[:max_expiries]
    if not expiries:
        raise RuntimeError("No QQQ option expiries returned")

    now = datetime.now(timezone.utc)
    positions: list[OptionPosition] = []

    for expiry in expiries:
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        expiry_years = max((expiry_dt - now).days, 1) / 365.0
        chain = ticker.option_chain(expiry)

        for side, frame in (("CALL", chain.calls), ("PUT", chain.puts)):
            for _, row in frame.iterrows():
                oi = row.get("openInterest", 0) or 0
                iv = row.get("impliedVolatility", 0) or 0
                if oi <= 0 or iv <= 0:
                    continue
                positions.append(
                    OptionPosition(
                        strike=float(row["strike"]),  # rescaled to NQ below
                        expiry_years=expiry_years,
                        option_type=side,
                        open_interest=int(oi),
                        implied_volatility=float(iv),
                    )
                )

    return positions, qqq_spot


def live_option_chain(nq_price: float) -> list[OptionPosition]:
    """
    Returns option positions with strikes rescaled onto NQ's price so
    engine.gex.aggregate_gex_by_strike() produces walls/flip in NQ points.

    Cached for `live_refresh_seconds` since option chain pulls are the
    heaviest calls in the system.
    """
    now = time.time()
    if yf is not None and now - _cache["fetched_at"] >= max(30, settings.live_refresh_seconds):
        try:
            raw_positions, qqq_spot = _fetch_chain()
            ratio = nq_price / qqq_spot if qqq_spot else 1.0
            scaled = [
                OptionPosition(
                    strike=round(p.strike * ratio / 5) * 5,  # snap to a clean 5pt grid
                    expiry_years=p.expiry_years,
                    option_type=p.option_type,
                    open_interest=p.open_interest,
                    implied_volatility=p.implied_volatility,
                )
                for p in raw_positions
            ]
            _cache.update(positions=scaled, ratio=ratio, fetched_at=now)
        except Exception as exc:
            logger.warning("live option chain fetch failed, reusing cache: %s", exc)
            _cache["fetched_at"] = now  # avoid hammering the API on repeated failures

    if not _cache["positions"]:
        # Cold start with no successful fetch yet — return nothing and let
        # derive_gex_summary() fall back to its own neutral default rather
        # than crash the request.
        return []

    return _cache["positions"]
