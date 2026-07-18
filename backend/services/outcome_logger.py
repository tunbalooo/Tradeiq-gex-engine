"""
Outcome logger — persists each CLOSED lifecycle trade and computes REAL
performance (win rate, avg R, profit factor, net PnL, equity curve) from
those recorded outcomes. Replaces the honest-but-empty zeros with genuine
tracked results as setups play out.

A trade is logged exactly once, when v0.4's SetupLifecycleService moves it
into a terminal state (TP2_HIT / TP1_HIT / STOPPED / EXPIRED / INVALIDATED).
Dedupe is by setup_id, so the 2s tick loop can't double-count.

R and $ PnL:
  - TP2_HIT  -> reward = |tp2 - entry| / risk           (full winner)
  - TP1_HIT  -> reward = |tp1 - entry| / risk           (partial, treated as
                a win at TP1 for scoring; refine to scale-out later)
  - STOPPED  -> -1R
  - EXPIRED / INVALIDATED -> not counted as win or loss (0R, excluded from
    win-rate denominator) because no trade was actually taken.
NQ = $20 / point.
"""

from __future__ import annotations

from datetime import datetime

from backend.core.database import SessionLocal
from backend.models.db_models import TradeOutcome
from backend.models.schemas import PerformanceSummary, TradeSetup

POINT_VALUE = 20.0
COUNTED = {"TP2_HIT", "TP1_HIT", "STOPPED"}  # actual taken trades (win/loss)


def log_outcome(setup: TradeSetup) -> None:
    """Record a terminal lifecycle setup once. Safe to call every tick."""
    state = getattr(setup, "order_state", None) or setup.status
    if state not in {"TP2_HIT", "TP1_HIT", "STOPPED", "EXPIRED", "INVALIDATED"}:
        return
    sid = getattr(setup, "setup_id", None)
    if not sid:
        return

    db = SessionLocal()
    try:
        if db.query(TradeOutcome).filter(TradeOutcome.setup_id == sid).first():
            return  # already logged

        risk = abs((setup.entry or 0) - (setup.stop_loss or 0)) or 1.0
        if state == "TP2_HIT":
            r = abs(setup.take_profit_2 - setup.entry) / risk
        elif state == "TP1_HIT":
            r = abs(setup.take_profit_1 - setup.entry) / risk
        elif state == "STOPPED":
            r = -1.0
        else:
            r = 0.0
        pnl = round(r * risk * POINT_VALUE, 2)

        db.add(TradeOutcome(
            setup_id=sid,
            closed_at=getattr(setup, "closed_at", None) or datetime.utcnow(),
            direction=setup.direction,
            entry=setup.entry, stop_loss=setup.stop_loss,
            take_profit_1=setup.take_profit_1, take_profit_2=setup.take_profit_2,
            outcome=state, result_r=round(r, 3), pnl=pnl,
        ))
        db.commit()
    finally:
        db.close()


def performance_summary() -> PerformanceSummary:
    """Real performance from logged outcomes; empty-safe (honest zeros)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(TradeOutcome)
            .filter(TradeOutcome.outcome.in_(list(COUNTED)))
            .order_by(TradeOutcome.closed_at.asc())
            .all()
        )
        if not rows:
            return PerformanceSummary(
                win_rate=0.0, trades=0, average_r=0.0, profit_factor=0.0,
                net_pnl=0.0, equity_curve=[0.0], simulated=False,
            )

        wins = [t for t in rows if t.result_r > 0]
        gross_win = sum(t.pnl for t in wins)
        gross_loss = -sum(t.pnl for t in rows if t.result_r < 0)
        equity, running = [0.0], 0.0
        for t in rows:
            running += t.pnl
            equity.append(round(running, 2))

        return PerformanceSummary(
            win_rate=round(len(wins) / len(rows) * 100, 1),
            trades=len(rows),
            average_r=round(sum(t.result_r for t in rows) / len(rows), 2),
            profit_factor=round(gross_win / gross_loss, 2) if gross_loss > 0 else round(gross_win, 2),
            net_pnl=round(running, 2),
            equity_curve=equity[-60:],
            simulated=False,
        )
    finally:
        db.close()
