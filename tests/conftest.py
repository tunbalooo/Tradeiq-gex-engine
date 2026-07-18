import os

# Keep tests isolated from live services and paid APIs.
os.environ["SIMULATED_MODE"] = "true"
os.environ["DATA_PROVIDER"] = "simulated"
os.environ["DATABASE_URL"] = "sqlite:///./data/test_tradeiq.db"
os.environ["ALLOW_PUBLIC_ADMIN"] = "true"

# Force Claude off during pytest, even when .env enables it.
os.environ["CLAUDE_ANALYSIS_ENABLED"] = "false"
os.environ.pop("ANTHROPIC_API_KEY", None)

# Prevent tests from calling external data providers.
os.environ.pop("DATABENTO_API_KEY", None)
os.environ.pop("FINNHUB_API_KEY", None)