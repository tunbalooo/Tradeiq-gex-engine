# TradeIQ GEX Engine v0.5

TradeIQ is a local/Railway NQ decision-support dashboard combining native NQ market data, estimated dealer GEX, EMA trend, liquidity, displacement/FVG, Fib/OTE, supply/demand, risk targets, lifecycle tracking, persistence, alerts, and research backtesting.

## v0.5 highlights

- Every sidebar item opens a working page: Dashboard, Chart, GEX Analysis, Confluence, Trade Setups, Alerts, Positions, Backtest, and Settings.
- One central trade-engine loop processes candles; dashboard reads no longer mutate trade state.
- Prevents retroactive fills by recording `armed_candle_time` and processing each closed candle once.
- Directional sequence validation: sweep → displacement → FVG within a configurable number of bars.
- True New York RTH filtering for VWAP, session high/low, standard deviation, and daily change.
- Databento historical range requests are clamped to available data.
- NQ option definitions are grouped by `underlying_id` to reduce mixing different futures books.
- PostgreSQL/Supabase support through `DATABASE_URL` and `psycopg`.
- Persistent setup history, lifecycle transitions, alerts, and performance statistics.
- Admin endpoints are protected with `ADMIN_TOKEN` by default.
- 2R fallback remains active when no valid market target is available.

## Start locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Databento live mode

Create `.env` from `.env.example` and set:

```env
DATA_PROVIDER=databento
SIMULATED_MODE=false
DATABENTO_API_KEY=db-your-key
```

Never commit `.env`.

## Supabase / PostgreSQL

Use the Supabase session-pooler connection string in Railway:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres?sslmode=require
```

## Railway

Start command:

```bash
sh -c 'python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}'
```

Set an `ADMIN_TOKEN` Railway variable. The Settings page uses that token only for refresh/reset actions.

## Tests

```powershell
python -m pytest -q
```

The test environment forces simulated data and does not call the paid Databento service.

## Important

GEX is estimated from options open interest, volatility/gamma assumptions, and dealer-side sign conventions. TradeIQ is decision support and research software, not a guarantee of profitability and not a live broker execution system.


## v0.9 chart-side setup
The full Chart page displays the active Trade Setup beside the chart. Fullscreen hides the setup panel automatically; exiting fullscreen restores it.

## Claude Market Analyst (optional)

The Chart page can stream a read-only explanation of the current TradeIQ setup. Claude receives a compact server-side snapshot and cannot change the deterministic engine's confidence score, trade plan, lifecycle state, GEX values, or session gate.

Add these values to your private `.env` and to Railway Variables:

```env
ANTHROPIC_API_KEY=your_private_key
ANTHROPIC_MODEL=claude-sonnet-5
CLAUDE_ANALYSIS_ENABLED=true
CLAUDE_ANALYSIS_INTERVAL_SECONDS=300
CLAUDE_FORCE_MIN_INTERVAL_SECONDS=60
CLAUDE_MAX_OUTPUT_TOKENS=700
CLAUDE_REQUEST_TIMEOUT_SECONDS=60
```

Never put `ANTHROPIC_API_KEY` in `frontend/app.js`, `frontend/trading_chart.js`, GitHub, or screenshots.
