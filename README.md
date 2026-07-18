# TradeIQ GEX Engine — Databento v0.4

TradeIQ is a local or Railway-hosted NQ decision-support dashboard. It combines native NQ options-derived GEX with trend, liquidity, displacement/FVG, Fib/OTE, supply/demand, VWAP, volatility and risk structure.

## What v0.4 does

- Streams NQ futures through Databento.
- Loads native CME NQ options definitions and open interest.
- Calculates Black-76 gamma and GEX by strike.
- Separately derives call wall and put wall.
- Reprices the option book to estimate gamma flip.
- Detects fresh multi-timeframe supply/demand zones and removes invalidated zones.
- Requires direction-specific liquidity sweeps and displacement.
- Detects GEX + OTE + supply/demand price clusters.
- Selects targets from market structure before using a 2R fallback.
- Separates preview setups from actionable armed limits.
- Freezes an armed trade plan and tracks fill, TP1, TP2, stop, invalidation and expiry.

> Confidence is a confluence score, not a guaranteed win probability.
> The app does not place broker orders.

## Local start

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn backend.main:app --reload
```

Open:

- Dashboard: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/api/health`

## Railway variables

Add these in Railway Variables, not GitHub:

```env
DATA_PROVIDER=databento
SIMULATED_MODE=false
DATABENTO_API_KEY=db-your-private-key
DATABENTO_DATASET=GLBX.MDP3
DATABENTO_FUTURES_SYMBOL=NQ.v.0
DATABENTO_OPTIONS_PARENT=NQ.OPT
DATABASE_URL=sqlite:////app/data/tradeiq.db
```

Recommended Railway start command:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

## Update GitHub and Railway

Copy this update over the existing repository without deleting `.git`, then run:

```powershell
git add .
git commit -m "Upgrade confluence, targets and trade lifecycle"
git push
```

Railway should redeploy automatically from the `main` branch.

See `CHANGELOG_v0.4.md` for the full update list.
