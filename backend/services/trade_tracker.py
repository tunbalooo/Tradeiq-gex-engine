"""
Trade tracker — turns the engine's setups into tracked paper trades and
computes REAL performance from actual TP/SL outcomes, replacing the old
hard-coded 'simulated week' sample.

How it works, each engine tick:
  1. If the current setup is actionable (has an entry + confidence above a
     threshold) and we don't already have an open trade for that signal,
     record a PENDING trade. Deduped by direction + rounded entry so the
     2-second tick loop doesn't spawn duplicates.
  2. PENDING -> ACTIVE when price trades through the limit entry.
  3. ACTIVE -> WIN when TP1 is hit, LOSS when SL is hit. Uses the latest
     candle's HIGH/LOW so an intrabar touch counts (not just closes).
  4. PENDING trades expire if never filled within FILL_WINDOW minutes.

Performance is then computed from CLOSED trades:
  win_rate, trades, average_r, profit_factor, net_pnl, equity_curve.

$ PnL uses NQ's $20 / point. Everything is paper-tracked in SQLite; nothing
is sent to a broker. R is measured against the setup's own risk (entry->stop).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Float, Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, SessionLocal
from backend.models.schemas import PerformanceSummary, TradeSetup

POINT_VALUE = 20.0          # NQ = $20 per index point
MIN_CONFIDENCE = 70.0       # only track setups the engine is reasonably sure of
FILL_WINDOW_MIN = 45        # cancel a pending limit if unfilled this long
DEDUPE_POINTS = 10          # same signal if entry within this many points


class TrackedTrade(Base):
    __tablename__ = "tracked_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    direction: Mapped[str] = mapped_column(String(10))
    entry: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    risk_points: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="PENDING", index=True)  # PENDING/ACTIVE/WIN/LOSS/EXPIRED
    result_r: Mapped[float] = mapped_column(Float, default=0.0)
    pnl: Mapped[float] = mapped_column(Float, default=0.0)


def _actionable(setup: TradeSetup) -> bool:
    return (
        setup.entry is not None
        and setup.stop_loss is not None
        and setup.take_profit_1 is not None
        and setup.confidence >= MIN_CONFIDENCE
        and setup.direction in ("LONG", "SHORT")
        and setup.status.startswith("WAITING")  # not SCANNING/DEVELOPING/INVALIDATED
    )


def process_tick(setup: TradeSetup, last_high: float, last_low: float, last_close: float) -> None:
    """Advance all open trades and maybe open a new one. Safe to call every tick."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        open_trades = db.query(TrackedTrade).filter(TrackedTrade.status.in_(["PENDING", "ACTIVE"])).all()

        for t in open_trades:
            if t.status == "PENDING":
                # expire stale limits
                if (now - t.created_at) > timedelta(minutes=FILL_WINDOW_MIN):
                    t.status = "EXPIRED"; t.closed_at = now
                    continue
                # fill when price trades through the limit
                filled = last_low <= t.entry <= last_high
                if filled:
                    t.status = "ACTIVE"
            if t.status == "ACTIVE":
                if t.direction == "LONG":
                    hit_sl = last_low <= t.stop_loss
                    hit_tp = last_high >= t.take_profit
                else:
                    hit_sl = last_high >= t.stop_loss
                    hit_tp = last_low <= t.take_profit
                # SL checked first: if both touch in one bar, resolve as a loss
                # (conservative — we can't know the intrabar order).
                if hit_sl:
                    _close(t, won=False, now=now)
                    continue
                if hit_tp:
                    _close(t, won=True, now=now)

        # maybe open a new trade
        if _actionable(setup):
            dupe = (
                db.query(TrackedTrade)
                .filter(
                    TrackedTrade.status.in_(["PENDING", "ACTIVE"]),
                    TrackedTrade.direction == setup.direction,
                    TrackedTrade.entry >= setup.entry - DEDUPE_POINTS,
                    TrackedTrade.entry <= setup.entry + DEDUPE_POINTS,
                )
                .first()
            )
            if not dupe:
                risk = abs(setup.entry - setup.stop_loss) or 1.0
                db.add(TrackedTrade(
                    direction=setup.direction,
                    entry=round(setup.entry, 2),
                    stop_loss=round(setup.stop_loss, 2),
                    take_profit=round(setup.take_profit_1, 2),
                    risk_points=round(risk, 2),
                    confidence=setup.confidence,
                    status="PENDING",
                ))
        db.commit()
    finally:
        db.close()


def live_status() -> dict | None:
    """Return the most relevant live trade state for the Setup Status label.

    Priority: an ACTIVE (filled) position first, else the most recent trade
    that just closed this cycle, else None. Shape:
      {"state": "ACTIVE"|"WIN"|"LOSS", "direction": "LONG"|"SHORT"}
    """
    db = SessionLocal()
    try:
        active = (
            db.query(TrackedTrade)
            .filter(TrackedTrade.status == "ACTIVE")
            .order_by(TrackedTrade.created_at.desc())
            .first()
        )
        if active:
            return {"state": "ACTIVE", "direction": active.direction}
        # Most recent close in the last 90s so we can briefly show the result.
        from datetime import timedelta
        recent = (
            db.query(TrackedTrade)
            .filter(TrackedTrade.status.in_(["WIN", "LOSS"]))
            .filter(TrackedTrade.closed_at.isnot(None))
            .order_by(TrackedTrade.closed_at.desc())
            .first()
        )
        if recent and recent.closed_at and (datetime.utcnow() - recent.closed_at) < timedelta(seconds=90):
            return {"state": recent.status, "direction": recent.direction}
        return None
    finally:
        db.close()


def _close(trade: TrackedTrade, won: bool, now: datetime) -> None:
    reward = abs(trade.take_profit - trade.entry)
    risk = trade.risk_points or 1.0
    trade.result_r = round(reward / risk, 3) if won else -1.0
    trade.pnl = round((reward if won else -risk) * POINT_VALUE, 2)
    trade.status = "WIN" if won else "LOSS"
    trade.closed_at = now


def performance_summary() -> PerformanceSummary:
    """Compute real performance from closed trades; empty-safe."""
    db = SessionLocal()
    try:
        closed = (
            db.query(TrackedTrade)
            .filter(TrackedTrade.status.in_(["WIN", "LOSS"]))
            .order_by(TrackedTrade.closed_at.asc())
            .all()
        )
        if not closed:
            return PerformanceSummary(
                win_rate=0.0, trades=0, average_r=0.0, profit_factor=0.0,
                net_pnl=0.0, equity_curve=[0.0], simulated=False,
            )

        wins = [t for t in closed if t.status == "WIN"]
        gross_win = sum(t.pnl for t in wins)
        gross_loss = -sum(t.pnl for t in closed if t.status == "LOSS")
        equity, running = [0.0], 0.0
        for t in closed:
            running += t.pnl
            equity.append(round(running, 2))

        return PerformanceSummary(
            win_rate=round(len(wins) / len(closed) * 100, 1),
            trades=len(closed),
            average_r=round(sum(t.result_r for t in closed) / len(closed), 2),
            profit_factor=round(gross_win / gross_loss, 2) if gross_loss > 0 else round(gross_win, 2),
            net_pnl=round(running, 2),
            equity_curve=equity[-60:],  # keep the sparkline light
            simulated=False,
        )
    finally:
        db.close()
