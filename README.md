# TradeIQ — NQ GEX Engine

A local-first NQ trading dashboard that combines simulated NQ candles, GEX levels, market structure, Fib/OTE, supply and demand, VWAP, standard-deviation levels, confidence scoring, and suggested limit-entry risk plans.

## What is connected in this build

- The full TradeIQ dashboard design supplied for the project
- FastAPI backend and interactive API documentation
- WebSocket updates every two seconds
- Accelerated simulated one-minute NQ feed
- Working 1m, 2m, 3m, 5m, 15m, 1h, and 4h chart aggregation
- 9/21/55 EMA chart overlays
- Black-76 gamma and strike-level GEX calculations using a synthetic options chain
- Call wall, put wall, gamma flip, positive/negative GEX levels, and gamma regime
- Automatic swing Fib with 0.618–0.786 OTE highlighting
- Multi-timeframe 5m, 15m, and 1H supply/demand detection
- Liquidity sweep and displacement checks
- VWAP and ±1 standard-deviation levels
- Transparent 100-point confluence score
- Suggested limit entry, stop loss, TP1, TP2, R:R, setup status, and expiry
- Chart overlays for the trade plan, zones, GEX, Fib, EMAs, VWAP, and standard deviation
- Recent alerts, news-calendar placeholders, and simulated performance display
- SQLite setup-history storage
- Unit and API tests

> **Two modes.** `SIMULATED_MODE=true` (default) runs a synthetic feed for development.
> Set `SIMULATED_MODE=false` in `.env` for **live mode**: real MNQ/NQ price and a real
> QQQ options chain (free, ~15-min delayed via yfinance), rescaled to NQ points for GEX.
> The calendar and performance panels remain placeholders in both modes. Live GEX is a
> QQQ proxy, not CME NQ options-on-futures dealer positioning — treat levels as context,
> not exact dealer flow. Not financial advice; backtest before trading real size.

## Easiest start on Windows

1. Extract the ZIP.
2. Open the extracted `Tradeiq-gex-engine` folder.
3. Double-click `start_windows.bat`.
4. When installation finishes, open `http://127.0.0.1:8000`.

## Manual start

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

### macOS/Linux

```bash
./start_mac_linux.sh
```

Then open:

- Dashboard: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/api/health`

## Useful endpoints

- `GET /api/dashboard`
- `GET /api/market/snapshot?timeframe=5&limit=1000`
- `GET /api/gex/summary`
- `GET /api/setup/current`
- `POST /api/setup/recalculate`
- `GET /api/setups/history`
- `WS /ws/market`

## Run tests

```bash
pytest -q
```

## Connecting real data later

The next live-data adapter must supply:

- NQ futures OHLCV
- Option strike and expiration
- Call/put classification
- Open interest and volume
- Implied volatility or enough option data to solve IV
- Option mark, bid/ask, or mid-price

Replace `SimulatedMarketDataService` and `mock_option_chain()` with the selected provider adapters. The frontend and strategy engines can remain unchanged.

## Project structure

```text
Tradeiq-gex-engine/
├── backend/
│   ├── api/
│   ├── core/
│   ├── models/
│   ├── services/
│   └── main.py
├── engine/
│   ├── confidence.py
│   ├── fib_ote.py
│   ├── gex.py
│   ├── market_structure.py
│   ├── risk_engine.py
│   └── supply_demand.py
├── frontend/
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── tests/
├── start_windows.bat
├── start_mac_linux.sh
└── requirements.txt
```

This software is for research and decision support. A confluence score is not a guaranteed probability of profit, and the application does not place live orders.
