import os

# Tests must never call paid external services.
os.environ["SIMULATED_MODE"] = "true"
os.environ["DATA_PROVIDER"] = "simulated"

os.environ["CLAUDE_ANALYSIS_ENABLED"] = "false"

os.environ.pop("DATABENTO_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)