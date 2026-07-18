from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Candle(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class GexLevel(BaseModel):
    type: str
    price: float
    gex: float | None = None
    strength: int = Field(default=3, ge=0, le=5)


class GexSummary(BaseModel):
    regime: Literal["POSITIVE", "NEGATIVE", "NEUTRAL"]
    gamma_flip: float
    put_wall: float
    call_wall: float
    net_gex: float
    levels: list[GexLevel]
    call_wall_gex: float | None = None
    put_wall_gex: float | None = None
    source: str = "simulated"
    updated_at: datetime | None = None
    contract_count: int = 0
    expiry_count: int = 0
    is_estimate: bool = True


class Zone(BaseModel):
    timeframe: str
    kind: Literal["SUPPLY", "DEMAND"]
    low: float
    high: float
    strength: int = Field(ge=1, le=5)
    fresh: bool = True
    touches: int = 0
    created_at: datetime | None = None
    displacement_score: float = 0.0
    invalidated: bool = False


class FibLevel(BaseModel):
    ratio: float
    price: float
    label: str


class MarketOverviewItem(BaseModel):
    symbol: str
    price: float
    change: float
    change_percent: float


class AlertItem(BaseModel):
    time: str
    title: str
    detail: str
    severity: Literal["positive", "negative", "warning", "info"] = "info"
    created_at: datetime | None = None


class NewsItem(BaseModel):
    time: str
    event: str
    impact: Literal["High", "Med", "Low"]
    source: str = "Finnhub"
    url: str | None = None
    summary: str | None = None
    published_at: datetime | None = None


class PerformanceSummary(BaseModel):
    win_rate: float
    trades: int
    average_r: float
    profit_factor: float
    net_pnl: float
    equity_curve: list[float]
    simulated: bool = True


class TradeSetup(BaseModel):
    setup_id: str
    symbol: str = "NQ"
    timestamp: datetime
    valid_until: datetime
    direction: Literal["LONG", "SHORT", "NONE"]
    confidence: float = Field(ge=0, le=100)
    confidence_components: dict[str, float]
    confidence_maximums: dict[str, float]
    signals: dict[str, Any]

    actionable: bool = False
    entry_valid: bool = False
    order_state: str = "PREVIEW_ONLY"
    armed_at: datetime | None = None
    armed_candle_time: datetime | None = None
    last_processed_candle_time: datetime | None = None
    filled_at: datetime | None = None
    closed_at: datetime | None = None
    outcome: str | None = None

    entry: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None
    take_profit_2: float | None = None
    risk_reward: float | None = None
    tp1_r: float | None = None
    tp2_r: float | None = None
    target_sources: dict[str, str] = Field(default_factory=dict)

    status: str
    rationale: list[str]
    gex: GexSummary
    zones: list[Zone]
    fib_levels: list[FibLevel]
    atr: float
    vwap: float
    standard_deviation_high: float
    standard_deviation_low: float

    cluster_score: float = 0.0
    cluster_low: float | None = None
    cluster_high: float | None = None
    cluster_gex_level: float | None = None
    cluster_gex_type: str | None = None
    selected_zone_low: float | None = None
    selected_zone_high: float | None = None
    selected_zone_timeframe: str | None = None


class DashboardMeta(BaseModel):
    overview: list[MarketOverviewItem]
    alerts: list[AlertItem]
    news: list[NewsItem]
    performance: PerformanceSummary


class EngineSnapshot(BaseModel):
    running: bool
    last_cycle_at: datetime | None = None
    last_processed_candle_time: datetime | None = None
    current_setup: TradeSetup | None = None
    last_error: str | None = None


class BacktestRequest(BaseModel):
    timeframe: int = Field(default=5, ge=1, le=240)
    minimum_score: float = Field(default=75, ge=0, le=100)
    target_r: float = Field(default=2.0, ge=0.5, le=10)
    max_bars: int = Field(default=1200, ge=100, le=2400)


class BacktestResult(BaseModel):
    generated_at: datetime
    trades: int
    wins: int
    losses: int
    expired: int
    win_rate: float
    average_r: float
    profit_factor: float
    net_r: float
    equity_curve: list[float]
    rows: list[dict[str, Any]]
