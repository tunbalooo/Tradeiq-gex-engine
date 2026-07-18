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

    # Provider selector: "yfinance" (free/delayed QQQ proxy) or "databento"
    # (native CME NQ via GLBX.MDP3). Databento is licensed for personal use
    # on your local machine — keep cloud/Railway on yfinance.
    data_provider: str = "yfinance"
    databento_api_key: str = ""
    databento_dataset: str = "GLBX.MDP3"
    databento_price_symbol: str = "NQ.v.0"   # continuous lead-month NQ future
    databento_options_parent: str = "NQ.OPT"  # options-on-futures parent

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
