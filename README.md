# TradeIQ Institutional Decision Platform v3.0.2


## v3.0.2 entry and chart stability

This release fixes the two problems visible in the v3.0.1 screenshots:

- **No limit despite a ranked setup:** entry models now use their own confirmation contracts instead of one universal liquidity-sweep/cluster gate. Monitoring begins at a model score of 58; a limit can arm at 72 after model-specific confirmation and common risk safety pass.
- **Unclean chart and noisy history:** Clean Chart mode is now on by default, extra zone/GEX labels are suppressed, the newest malformed wick is filtered, and repeated polling of the same closed candle cannot generate alternating setup-history rows.

TradeIQ still does not manufacture a trade. A limit requires a valid resting entry, target space, at least 2R to TP2, the confidence floor and the selected model's deterministic confirmations.


## v3.0.1 chart and candlestick hotfix

This release fixes small-timeframe chart distortion by separating candle autoscaling from distant analytical levels, rejecting malformed/replayed market records, sorting and deduplicating bars before aggregation, and remembering each symbol/timeframe viewport.

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

TradeIQ no longer blocks the instrument selector while a full Databento history request finishes. On a first visit to a market, the interface switches immediately into **DATABENTO SYNC** mode and waits for real Databento candles. It no longer injects simulated preview prices into a live chart. Automatic Claude analysis, indicators that require full history, and order arming remain disabled until coherent real/cached history is ready.

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

## v1.6 mobile reliability

Mobile and iPad charts wait until the chart pane has a real width and height before initialization, resize explicitly on rotation and pane changes, and use a built-in Canvas fallback if the external Lightweight Charts library cannot be reached. Finnhub cards display weekday, date, time, and ET timezone.

## v1.8 clean mobile terminal and GEX-by-strike

- Mobile chart rendering now uses TradeIQ's native Canvas engine on phone and tablet widths. It draws real backend candles, volume, EMAs, active GEX levels, VWAP, supply/demand shading, and the current trade plan without depending on a third-party CDN.
- Touch drag, chart zoom buttons, pan buttons, recenter, fit, candle/line mode, and fullscreen remain available.
- The mobile interface follows a restrained terminal layout with a compact symbol header, standard timeframe strip, full-height chart, flat bottom navigation, and simplified Setup, Assistant, News, and GEX screens.
- Mobile News is split into `Economic Calendar` and `Headlines` tabs. Economic releases are grouped by scheduled day/date and show their scheduled ET time, impact, forecast, and previous value.
- The desktop GEX Analysis page now includes `GEX Exposure by Strike`, using positive green bars, negative red bars, and a dashed gamma-flip marker.
- The API GEX object now exposes `by_strike` rows containing `strike`, `call_gex`, `put_gex`, and `net_gex`.

Desktop charts continue to use TradingView Lightweight Charts 5.2. Mobile and tablet charts intentionally use the built-in Canvas renderer for reliability in Safari and installed PWAs.

## v1.9 mobile price navigation and chart stability

The mobile chart now supports full two-dimensional navigation: drag horizontally through time, drag vertically through price, and drag the right price scale to zoom. Double-tap, Auto, Fit or Real time restores automatic price scaling. TradeIQ also retains validated candle history by symbol and timeframe so a sparse live tick cannot collapse a full chart into one candle.

## v2.0 locked trade plans

TradeIQ separates a continuously recalculated **candidate** from an **armed setup**. Candidate entry, stop and target calculations are kept off the chart. The risk box and Entry/SL/TP lines appear only when the engine transitions to `WAITING_FOR_LIMIT`. Those trade levels are then frozen for the life of the setup and cannot follow the current price.


## v2.1 Watching lifecycle

A developing setup now enters `WATCHING` before an order is armed. TradeIQ shows the fixed watched direction and entry, such as `WATCHING LONG @ 28,750.25`, but hides SL, targets and the risk box. After all mandatory confirmations pass, it transitions to `WAITING_FOR_LIMIT` and locks the complete trade plan.


## v2.2 stable chart core and reference levels

TradeIQ now enforces one coherent futures price regime per chart. Simulated preview history is never stitched to live Databento ticks. Historical bars are validated, deduplicated and compared with the live stream before they are merged. When a contract/provenance mismatch is detected, the mixed history is rejected and the chart displays a clear live-only syncing state rather than drawing a giant wick or connecting two unrelated price ranges.

The market snapshot API now exposes `history_ready`, `history_source`, `data_quality`, `raw_symbol`, and `futures_symbol`. Desktop and mobile charts use those fields to keep trade levels and indicators hidden while history is incomplete. iPhone fullscreen also has a CSS viewport fallback when Safari declines the native Fullscreen API.

The GEX display now mirrors the requested institutional level layout:

- Gamma Resistance / Call Wall
- Gamma Flip
- Maximum Pain, only when real option open-interest data is available
- Put Support / Put Wall
- Ranked Strong +GEX and Strong -GEX levels
- RTH Equilibrium
- VWAP and standard-deviation context

Maximum Pain is calculated by minimizing aggregate option-holder intrinsic payout across candidate settlement strikes. It is never fabricated from fallback net-GEX values.


## Watch expiry integrity (v2.3)

A `WATCHING` candidate receives immutable `watch_started_at` and `watch_expires_at` timestamps. Engine refreshes may update confidence and confluence context but cannot renew the watch. When the deadline passes without confirmation, the watch expires and the identical candidate remains suppressed until market structure produces a materially new setup.



## v2.4 stable mobile chart and unambiguous execution states

- iPhone, iPad and desktop now use the same official TradingView Lightweight Charts 5.2 engine. The custom mobile Canvas renderer remains only as an emergency CDN fallback.
- Realtime bars use `series.update`; full-history replacement uses `setData` only when required. User zoom/pan is preserved across refreshes, and the chart no longer auto-scales to distant GEX levels.
- `WATCHING` is presented as **MONITORING ONLY**. The monitored trigger is stored separately as `watch_trigger`; entry, stop and targets remain empty until `WAITING_FOR_LIMIT`.
- If price touches the monitor trigger before confirmation, the state becomes `UNCONFIRMED_TOUCH`: no order and no fill are recorded.
- `WAITING_FOR_LIMIT` is the first state that displays the locked limit, SL, TP1, TP2 and risk box. A later touch changes the state to `FILLED` while those levels remain fixed.


## v2.5 Claude lifecycle explanations

- Claude now acts as a lifecycle commentator for the deterministic TradeIQ engine rather than giving a generic market recap.
- `WATCHING` explanations state why the engine is monitoring, which confirmations are present, which are missing, and what must occur before a limit plan can be armed.
- `WAITING_FOR_LIMIT` explanations cover why the plan qualified, why the locked entry was selected, what the stop invalidates, and the supplied sources for TP1 and TP2.
- `FILLED`, `TP1_HIT`, `TP2_HIT`, `STOPPED`, `EXPIRED`, `INVALIDATED`, and `UNCONFIRMED_TOUCH` each receive an automatic explanation based on the engine's recorded transition reason.
- Lifecycle events are queued when they occur while Claude is already streaming, so a fast fill or cancellation is not silently missed.
- Claude remains read-only and cannot change confidence, levels, setup states, session gating, or order handling.


## v2.6 persistent setup memory and lifecycle timeline

- TradeIQ restores the newest active `WATCHING`, `WAITING_FOR_LIMIT`, `FILLED`, or `TP1_HIT` setup from the database when the FastAPI service restarts. Railway deployments no longer silently erase the setup lifecycle.
- The restored setup keeps its original setup ID, watched trigger, locked trade levels, expiry, fill state, transition reason, and last processed candle time. The first live engine cycle then advances the same object normally.
- `GET /api/setups/{setup_id}/timeline` exposes the deterministic transition history in chronological order.
- Desktop and mobile setup panels show a compact lifecycle memory timeline.
- Claude receives the recent lifecycle timeline for historical context while the latest recorded transition remains authoritative. Claude is still read-only.


## v3.0 institutional decision platform

- Deterministic Decision Brain ranks twelve entry models and exposes a primary model plus qualified backups.
- Institutional confidence is transparent across Trend, Structure, GEX, Liquidity, Momentum, Volume and Session categories.
- GEX reference levels remain locked to the current option-position snapshot instead of re-centering on every tick.
- TP1 can secure a partial position and move the runner stop to break-even while preserving the immutable initial stop.
- Setup history includes model, grade, initial/active stop, management state, MFE, MAE and result.
- Read-only model analytics are available at `GET /api/analytics/summary`.
- Claude receives the exact model-selection and management lifecycle context but cannot alter it.

New endpoints:

```text
GET /api/decision-brain
GET /api/entry-models
GET /api/analytics/summary
```

Current verification target:

```text
104 passed
```

See the four living specifications in the project root for the current product, trading engine, UI/UX and roadmap definitions.


## v3.0.3 Fib Pullback Continuation and watch execution

- Added **Fib Pullback Continuation** as a model separate from OTE. It monitors a 50%–61.8% retracement, requires a completed directional rejection/reclaim, and uses the confirmation candle's body midpoint as the locked resting limit.
- A watch-line touch now creates a visible `TRIGGER_TOUCHED` phase. The UI says `CONFIRMING LONG/SHORT` and explicitly states that no order or fill exists.
- The engine opens a finite model-confirmation window. Confirmation arms the locked plan; structural failure invalidates it; timeout records `UNCONFIRMED_TOUCH` with the exact reason.
- Completed candles drive model confirmation. The newest live candle drives watch touches, locked-limit fills, stops and targets.
- Same-candle sequencing guards prevent price movement from before the order/active stop existed from being counted as a later fill or stop.

Configuration:

```env
WATCH_CONFIRMATION_MINUTES=5
```

Current local verification target:

```text
123 passed
```
