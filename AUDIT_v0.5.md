# TradeIQ v0.5 Audit

## Verified
- 11 automated tests pass.
- Python modules compile.
- Frontend JavaScript syntax passes Node validation.
- FastAPI starts and `/api/health` plus `/api/dashboard` return 200.
- All nine sidebar pages have working API-backed content.
- GET/dashboard/WebSocket reads do not advance lifecycle state.
- The engine processes one closed candle at a time.
- The arming candle cannot retroactively fill the limit.
- RTH VWAP/session levels use America/New_York boundaries.
- Supabase/PostgreSQL is supported through `DATABASE_URL`.
- Admin reset and GEX refresh endpoints require `ADMIN_TOKEN` unless explicitly disabled.

## Engine status
- GEX, OTE, supply/demand, EMA trend, directional sweep, directional displacement/FVG, cluster scoring, target selection, and 2R fallback are connected.
- Setup transitions and outcomes are saved to PostgreSQL/Supabase or local SQLite.
- Positions page displays lifecycle-tracked filled setups.
- Performance uses completed stored outcomes, not invented values.

## Remaining limitations
- Broker order placement is intentionally not connected.
- GEX dealer positioning remains an estimate based on options data and sign assumptions.
- The built-in backtest page is an EMA/ATR research baseline; full historical GEX reconstruction is not yet implemented.
- Economic news requires a separate calendar provider.
