from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TradeIQ GEX Engine"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/tradeiq.db"
    simulated_mode: bool = True
    simulation_symbol: str = "NQ"
    simulation_start_price: float = 24892.25
    update_interval_seconds: int = 2

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
