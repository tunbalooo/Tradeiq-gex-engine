# TradeIQ Multi-Market GEX Engine v1.5

TradeIQ is a FastAPI and browser-based futures decision-support dashboard for:

- NQ — E-mini Nasdaq-100
- MNQ — Micro E-mini Nasdaq-100
- ES — E-mini S&P 500
- MES — Micro E-mini S&P 500
- GC — COMEX Gold
- MGC — Micro Gold

The active market selector updates candles, EMA structure, supply/demand, Fib/OTE, trade levels, Claude analysis, Finnhub relevance filtering, session rules, tick size, and GEX metadata. During the current single-user development stage, the selected symbol is global for the running server.


## Mobile and iPad workspace

TradeIQ v1.5 keeps the desktop workstation and adds a connected responsive interface for phones and tablets. It is not a separate mock application: the mobile Chart, Setup, Claude, News, and GEX views read the same live FastAPI endpoints, WebSocket updates, instrument selector, session gate, engine score, Databento state, Finnhub feed, and Claude stream as the desktop dashboard.

- **Phone:** fixed bottom navigation for Chart, Setup, Claude, News, and GEX.
- **iPad portrait:** full-width chart with switchable analysis panes.
- **iPad landscape:** chart and analysis rail share the screen.
- **PWA:** installable from supported browsers; iPhone and iPad can use Share → Add to Home Screen.
- **Touch charting:** pinch zoom, horizontal drag, kinetic scrolling, overlay toggles, recenter, fit, and fullscreen.
- **Safe continuity:** mobile layout does not alter confidence, actionability, order lifecycle, GEX calculations, or Claude permissions.

The supplied mobile concept was used as the visual direction. TradeIQ continues using its existing Lightweight Charts 5.2 integration rather than embedding the pasted minified 4.2 library or mock candle generator.

## What a preview means

A `PREVIEW_ONLY` setup is a watch-only candidate generated from the latest available engine data. It is not a prediction, scheduled trade, or guarantee that price will reach the displayed levels. A preview becomes an armed `WAITING_FOR_LIMIT` plan only when live/cached market data is ready, the session gate permits trading, and every mandatory engine condition passes.

## Fast market switching

TradeIQ no longer blocks the instrument selector while a full Databento history request finishes. On a first visit to a market, the interface switches immediately into **DATABENTO SYNC** mode, shows a clearly labelled local preview, and backfills real history in the background. Automatic Claude analysis and order arming remain disabled until the real/cached history is ready.

After a market has loaded once, its candles are retained in an in-memory cache for 30 minutes, so switching back is normally sub-second. Finnhub's general-news feed is also downloaded once and filtered locally for NQ, ES, and Gold instead of making a separate network request for each symbol.

Optional prewarming is disabled by default to avoid multiplying Databento historical usage on every Railway deployment. It can be enabled with:

```env
DATABENTO_PREWARM_MARKETS=true
```

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
- Claude is read-only and cannot modify confidence, entries, stops, targets, GEX, or lifecycle state. Fallback GEX is a reliability warning, not an independent execution gate.
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
DATABENTO_MARKET_CACHE_SECONDS=1800
DATABENTO_PREWARM_MARKETS=false
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
