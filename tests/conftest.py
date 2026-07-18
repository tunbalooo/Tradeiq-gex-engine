import os
os.environ["SIMULATED_MODE"] = "true"
os.environ["DATA_PROVIDER"] = "simulated"
os.environ["DATABASE_URL"] = "sqlite:///./data/test_tradeiq.db"
os.environ["ALLOW_PUBLIC_ADMIN"] = "true"
os.environ.pop("DATABENTO_API_KEY", None)
