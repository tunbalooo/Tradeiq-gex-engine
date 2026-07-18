# TradeIQ Multi-Market GEX Engine v1.2

TradeIQ is a FastAPI and browser-based futures decision-support dashboard for:

- NQ — E-mini Nasdaq-100
- MNQ — Micro E-mini Nasdaq-100
- ES — E-mini S&P 500
- MES — Micro E-mini S&P 500
- GC — COMEX Gold
- MGC — Micro Gold

The active market selector updates candles, EMA structure, supply/demand, Fib/OTE, trade levels, Claude analysis, Finnhub relevance filtering, session rules, tick size, and GEX metadata. During the current single-user development stage, the selected symbol is global for the running server.

## GEX mapping

| Chart | Futures feed | Options book used for GEX |
|---|---|---|
| NQ | `NQ.v.0` | `NQ.OPT` |
| MNQ | `MNQ.v.0` | parent `NQ.OPT` |
| ES | `ES.v.0` | `ES.OPT` |
| MES | `MES.v.0` | parent `ES.OPT` |
| GC | `GC.v.0` | `OG.OPT` |
| MGC | `MGC.v.0` | parent `OG.OPT` |

For micro charts, the interface explicitly labels the GEX as parent-market exposure. Native GEX still depends on eligible Databento option definitions, open interest, and account entitlement. If native data is unavailable, TradeIQ clearly displays the fallback estimate.

## Safety boundaries

- Session status never changes the confidence score.
- The session gate only controls whether a new setup is actionable or can be armed.
- Claude is read-only and cannot modify confidence, entries, stops, targets, GEX, or lifecycle state.
- Finnhub news is informational and does not change engine scoring.
- Broker execution is not enabled.

## Start locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Environment

Copy `.env.example` to `.env`. Never commit `.env`.

For live Databento candles and native GEX attempts:

```env
DATA_PROVIDER=databento
SIMULATED_MODE=false
DEFAULT_SYMBOL=NQ
DATABENTO_API_KEY=your_private_key
```

For Finnhub news:

```env
FINNHUB_API_KEY=your_private_key
```

For Claude analysis:

```env
ANTHROPIC_API_KEY=your_private_key
ANTHROPIC_MODEL=claude-sonnet-5
CLAUDE_ANALYSIS_ENABLED=true
```

## Railway

Start command:

```bash
sh -c 'python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}'
```

Existing Railway secrets remain unchanged. Add `DEFAULT_SYMBOL=NQ` only when a specific startup market is desired; NQ is already the default.

## API additions

```text
GET  /api/instruments
POST /api/market/symbol   body: {"symbol":"ES"}
```

The selector endpoint is intentionally global while TradeIQ is a single-user development deployment. Per-user symbol state should be moved to user sessions or Supabase when authentication is introduced.

## Tests

```powershell
python -m pytest -q
```

The test environment forces simulated data and disables paid external services.

## Important

GEX is estimated from option open interest, gamma/volatility assumptions, contract multipliers, and an assumed dealer-side sign. It is decision-support information, not a guarantee of profitability.
