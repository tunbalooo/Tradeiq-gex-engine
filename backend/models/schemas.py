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


class GexStrike(BaseModel):
    strike: float
    call_gex: float = 0.0
    put_gex: float = 0.0
    net_gex: float = 0.0


class GexSummary(BaseModel):
    regime: Literal["POSITIVE", "NEGATIVE", "NEUTRAL"]
    gamma_flip: float
    put_wall: float
    call_wall: float
    net_gex: float
    levels: list[GexLevel]
    by_strike: list[GexStrike] = Field(default_factory=list)
    call_wall_gex: float | None = None
    put_wall_gex: float | None = None
    max_pain: float | None = None
    gamma_resistance: float | None = None
    gamma_support: float | None = None
    source: str = "simulated"
    updated_at: datetime | None = None
    contract_count: int = 0
    expiry_count: int = 0
    is_estimate: bool = True
    source_symbol: str | None = None
    applied_to_symbol: str | None = None
    options_parent: str | None = None
    source_label: str | None = None
    is_parent_market: bool = False
    dealer_bias: str = "NEUTRAL"
    positive_gamma_percent: float = 0.0
    negative_gamma_percent: float = 0.0
    top_gamma_nodes: list[dict[str, Any]] = Field(default_factory=list)
    level_meanings: dict[str, str] = Field(default_factory=dict)


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


class EconomicEvent(BaseModel):
    scheduled_at: datetime
    event: str
    impact: Literal["High", "Med", "Low"]
    country: str = "US"
    actual: Any | None = None
    estimate: Any | None = None
    previous: Any | None = None
    unit: str | None = None
    source: str = "Finnhub Economic Calendar"


class PerformanceSummary(BaseModel):
    win_rate: float
    trades: int
    average_r: float
    profit_factor: float
    net_pnl: float
    equity_curve: list[float]
    simulated: bool = True




class EntryModelScore(BaseModel):
    key: str
    name: str
    direction: Literal["LONG", "SHORT", "NONE"]
    score: float = Field(ge=0, le=100)
    eligible: bool = False
    priority: int = 50
    trigger_price: float | None = None
    invalidation_price: float | None = None
    reason: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


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

    # TradeIQ Decision Brain and deterministic model ranking.
    primary_entry_model: str | None = None
    primary_entry_model_key: str | None = None
    primary_model_score: float = 0.0
    entry_model_scores: list[EntryModelScore] = Field(default_factory=list)
    alternative_entry_models: list[str] = Field(default_factory=list)
    model_selection_reason: str | None = None
    model_selected_at: datetime | None = None
    model_switch_count: int = 0
    confidence_grade: str = "AVOID"
    institutional_confidence_components: dict[str, float] = Field(default_factory=dict)
    institutional_confidence_maximums: dict[str, float] = Field(default_factory=dict)

    actionable: bool = False
    entry_valid: bool = False
    order_state: str = "PREVIEW_ONLY"
    watch_started_at: datetime | None = None
    watch_expires_at: datetime | None = None
    watch_trigger: float | None = None
    armed_at: datetime | None = None
    armed_candle_time: datetime | None = None
    last_processed_candle_time: datetime | None = None
    filled_at: datetime | None = None
    closed_at: datetime | None = None
    outcome: str | None = None

    # Professional management state. The original stop remains immutable while
    # active_stop_loss can advance to break-even after TP1.
    initial_stop_loss: float | None = None
    active_stop_loss: float | None = None
    management_state: str = "FLAT"
    partial_exit_percent: float = 50.0
    tp1_hit_at: datetime | None = None
    breakeven_at: datetime | None = None
    runner_active: bool = False
    max_favorable_excursion_points: float = 0.0
    max_adverse_excursion_points: float = 0.0
    management_actions: list[dict[str, Any]] = Field(default_factory=list)

    # Latest deterministic lifecycle transition. Claude receives these fields so
    # it can explain exactly why the engine is monitoring, arming, filling,
    # cancelling, expiring, stopping, or taking profit without inventing a cause.
    last_transition_from: str | None = None
    last_transition_to: str | None = None
    last_transition_reason: str | None = None
    last_transition_at: datetime | None = None
    last_transition_price: float | None = None

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
    economic_events: list[EconomicEvent] = Field(default_factory=list)
    economic_calendar_status: dict[str, Any] = Field(default_factory=dict)
    performance: PerformanceSummary


class EngineSnapshot(BaseModel):
    running: bool
    last_cycle_at: datetime | None = None
    last_processed_candle_time: datetime | None = None
    current_setup: TradeSetup | None = None
    last_error: str | None = None
    restored_setup_id: str | None = None
    restored_at: datetime | None = None


class MarketSymbolRequest(BaseModel):
    symbol: str


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
