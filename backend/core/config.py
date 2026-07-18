from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TradeIQ GEX Engine"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/tradeiq.db"

    data_provider: str = "simulated"
    simulated_mode: bool = True
    simulation_symbol: str = "NQ"
    simulation_start_price: float = 24892.25
    update_interval_seconds: int = 2
    engine_cycle_seconds: int = 2

    databento_api_key: str | None = None
    databento_dataset: str = "GLBX.MDP3"
    databento_futures_symbol: str = "NQ.v.0"
    databento_options_parent: str = "NQ.OPT"
    databento_history_days: int = 7
    databento_history_limit: int = 2400

    gex_refresh_seconds: int = 300
    gex_reprice_seconds: int = 30
    gex_max_dte: int = 45
    gex_strike_range_points: float = 700.0
    gex_expiry_count: int = 6
    gex_default_iv: float = 0.20
    gex_risk_free_rate: float = 0.045
    nq_contract_multiplier: int = 20

    setup_actionable_score: float = 75.0
    setup_expiry_minutes: int = 30
    cluster_min_score: float = 0.65
    cluster_tolerance_atr: float = 0.25
    nq_tick_size: float = 0.25
    event_sequence_max_bars: int = 4
    event_max_age_bars: int = 12

    admin_token: str | None = None
    allow_public_admin: bool = False

    finnhub_api_key: str | None = None
    finnhub_news_refresh_seconds: int = 300
    finnhub_request_timeout_seconds: float = 12.0

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    claude_analysis_enabled: bool = False
    claude_analysis_interval_seconds: int = 300
    claude_force_min_interval_seconds: int = 60
    claude_max_output_tokens: int = 700
    claude_request_timeout_seconds: float = 60.0

    rth_timezone: str = "America/New_York"
    rth_start_hour: int = 9
    rth_start_minute: int = 30
    rth_end_hour: int = 16
    rth_end_minute: int = 0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def use_databento(self) -> bool:
        return (
            self.data_provider.lower() == "databento"
            and not self.simulated_mode
            and bool(self.databento_api_key)
        )


settings = Settings()
