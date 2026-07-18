import os

os.environ["SIMULATED_MODE"] = "true"
os.environ["DATA_PROVIDER"] = "simulated"
os.environ["DATABASE_URL"] = "sqlite:///./data/test_tradeiq.db"
os.environ["ALLOW_PUBLIC_ADMIN"] = "true"
os.environ["DEFAULT_SYMBOL"] = "NQ"

# Keep paid/external services disabled in tests even when a local .env enables them.
os.environ["CLAUDE_ANALYSIS_ENABLED"] = "false"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("DATABENTO_API_KEY", None)
os.environ.pop("FINNHUB_API_KEY", None)
