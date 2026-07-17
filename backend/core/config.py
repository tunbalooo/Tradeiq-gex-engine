from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TradeIQ GEX Engine"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/tradeiq.db"
    simulated_mode: bool = True
    simulation_symbol: str = "NQ"
    simulation_start_price: float = 24892.25
    update_interval_seconds: int = 2

    # Live mode (SIMULATED_MODE=false) — free/delayed data via yfinance.
    # See backend/services/live_market_data.py and live_options.py.
    live_price_symbol: str = "MNQ=F"
    live_options_symbol: str = "QQQ"
    live_refresh_seconds: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
