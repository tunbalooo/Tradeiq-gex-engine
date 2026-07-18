# v0.5 — Full Pages + Safe Engine

## Frontend
- Added functional SPA pages for all sidebar navigation entries.
- Added advanced chart overlays and timeframe controls.
- Added GEX profile, confluence breakdown, setup history, alert center, position monitor, backtest lab, and runtime settings pages.
- Added protected admin actions for GEX refresh and setup reset.

## Backend
- Replaced request-driven lifecycle mutation with a single central background engine.
- Added closed-candle deduplication and armed-candle protection.
- Added persistent setup, transition, alert, and performance storage.
- Added Supabase/PostgreSQL compatibility.
- Added ordered sweep/displacement/FVG sequence validation.
- Added RTH session calculations.
- Added Databento availability-range clamping.
- Added dominant `underlying_id` filtering for NQ option definitions.
- Added all page APIs and a deterministic research backtest endpoint.
- Added admin endpoint protection.

## Validation
- 11 automated tests pass.
- API startup and dashboard smoke tests pass in simulated test mode.
