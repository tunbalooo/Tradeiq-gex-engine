# TradeIQ v1.0 — Chart UI + Claude Analyst

## Chart page
- Restyled only the full Chart page using the supplied TradeIQ chart interface.
- Keeps the dashboard page unchanged.
- Keeps the TradingView Lightweight Charts interaction layer: scroll zoom, drag pan, crosshair, price-scale control, fit, real-time recenter, fullscreen, horizontal drawing line, candle/line view, and overlay toggles.
- Keeps live Databento candles and TradeIQ overlays for EMA, GEX, Fib/OTE, supply/demand, VWAP/standard deviation, entry, stop, TP1, and TP2.
- Keeps the live Trade Setup beside the chart.
- Fullscreen hides the complete side rail and gives the chart the full display.

## Claude Market Analyst
- Adds a read-only Claude analyst below the chart-side Trade Setup.
- Streams a compact explanation of bias, status, observable evidence, missing conditions, risk, and action.
- Uses the existing TradeIQ snapshot; Claude cannot change confidence, entry, stop, targets, lifecycle state, GEX values, session rules, or place orders.
- Warns when native GEX is unavailable and the engine is using fallback estimates.
- Uses server-side `ANTHROPIC_API_KEY`; no API key is exposed to browser JavaScript.
- Adds global caching and request throttling to reduce API cost and public-endpoint abuse.
- Runs on chart open, important setup-state changes, every five minutes while Auto is enabled, or by the Analyze Now button.

## Environment variables
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL=claude-sonnet-5`
- `CLAUDE_ANALYSIS_ENABLED=true`
- `CLAUDE_ANALYSIS_INTERVAL_SECONDS=300`
- `CLAUDE_FORCE_MIN_INTERVAL_SECONDS=60`
- `CLAUDE_MAX_OUTPUT_TOKENS=700`
- `CLAUDE_REQUEST_TIMEOUT_SECONDS=60`
