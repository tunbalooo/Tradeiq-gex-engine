from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class TradeSetupRecord(Base):
    __tablename__ = "trade_setups_v2"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    setup_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), default="NQ")
    direction: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float)
    actionable: Mapped[bool] = mapped_column(Boolean, default=False)
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="SCANNING")
    order_state: Mapped[str] = mapped_column(String(40), default="PREVIEW_ONLY")
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    result_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_sources: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence_components: Mapped[dict] = mapped_column(JSON, default=dict)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    gex_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    setup_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class SetupTransitionRecord(Base):
    __tablename__ = "setup_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    setup_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    candle_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    previous_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_state: Mapped[str] = mapped_column(String(40))
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class AlertRecord(Base):
    __tablename__ = "engine_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    setup_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="info")
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
