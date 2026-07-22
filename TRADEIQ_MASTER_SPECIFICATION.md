# TradeIQ Master Specification

**Product version:** 3.0.8-connection-gex-resilience  
**Document version:** 3.0.8  
**Status:** Living source of truth

## 1. Product Purpose

TradeIQ is an institutional-style futures decision-support platform for NQ/MNQ, ES/MES, GC/MGC and later CL, Forex and Crypto. It combines deterministic market structure, GEX, liquidity, supply/demand, OTE, VWAP, EMA alignment and risk logic.

TradeIQ answers:

> Where is institutional participation likely, what is the engine waiting for, and what invalidates the plan?

It is not a broker, profit guarantee or autonomous AI trader.

## 2. Authority Boundaries

- **TradeIQ deterministic engine:** owns setup creation, scoring, state changes, entries, stops, targets and management rules.
- **Decision Brain:** ranks eligible entry models and selects the primary/backup path.
- **Claude:** reads recorded engine state and explains it. Claude cannot modify any trading field.
- **UI:** displays engine state and never creates its own setup logic.

## 3. Lifecycle

`PREVIEW_ONLY → WATCHING[WAITING_FOR_PRICE → TRIGGER_TOUCHED] → WAITING_FOR_LIMIT → FILLED → TP1_HIT → TP2_HIT/STOPPED`

Terminal alternatives:

- `EXPIRED`
- `INVALIDATED`
- `UNCONFIRMED_TOUCH`

A `WATCHING → WATCHING` event records a deterministic switch to a stronger secondary entry model.

## 4. Implemented v3.0–v3.0.6 Modules

- Live/historical market data service.
- GEX service with snapshot-stable dealer levels.
- Supply/demand and market-structure engines.
- OTE and risk engines.
- Persistent setup memory and lifecycle timeline.
- Claude lifecycle explanation queue.
- Decision Brain and 13-model ranking.
- Institutional confidence categories.
- TP1 partial, break-even runner and excursion tracking.
- Read-only model analytics.
- Responsive desktop/mobile web UI.


### Chart and market-data integrity (v3.0.1)

- Visible candle OHLC controls automatic price scaling; distant GEX, Fib, zone and trade levels no longer compress 1m/2m candles.
- Historical and live candles are normalized, deduplicated and sorted before aggregation.
- Replayed out-of-order Databento records are merged into their original minute or ignored instead of being appended out of sequence.
- Corrupt OHLC records and isolated giant wicks are rejected before reaching the chart.
- Each symbol/timeframe/chart combination retains its own viewport.

### Entry and lifecycle stability (v3.0.2)

- Every entry model is evaluated by a model-specific confirmation contract.
- A Liquidity Sweep model requires sweep/displacement/sequence evidence; OTE, EMA, VWAP, zone and FVG models are not forced through that unrelated gate.
- The selected model may provide the preferred resting entry and structural invalidation used by the risk engine.
- Monitoring and limit arming use separate thresholds.
- Model/direction replacement evidence is counted only on distinct closed candles, preventing two-second polling churn.
- Setup History exposes meaningful lifecycle objects rather than every transient preview.
- Clean Chart mode is the default and preserves the important institutional context without burying candles.

### Fib pullback and watch execution (v3.0.3)

- Fib Pullback Continuation is a separate model from anticipatory OTE.
- A directional impulse defines a 50%–61.8% monitoring zone.
- A completed rejection/reclaim candle is required before execution can arm.
- The executable limit uses the confirmation candle's 50% body midpoint.
- Structural pullback failure, not an arbitrary Fib ratio, defines invalidation.
- A live touch of a watch line immediately changes the visible phase to `TRIGGER_TOUCHED` while remaining explicitly **not an order**.
- The engine opens a finite confirmation window, then arms, invalidates or records `UNCONFIRMED_TOUCH` with an exact reason.
- Completed candles drive model confirmation; the newest live candle drives touches, fills, stops and targets.
- Observation snapshots prevent pre-watch, pre-arm, pre-fill or pre-break-even price extremes from being treated as later events while still detecting new same-candle crossings.


### Institutional Trade Desk and cross-market radar (v3.0.4)

- The full chart is now branded as the **TradeIQ Institutional Trade Desk** and receives the largest share of the desktop workspace.
- Trade Setup, Claude and Market Radar are mutually exclusive right-rail tabs. Only one pane is visible at a time, preventing Claude from overlapping setup information.
- The entire rail can be collapsed to create a chart-first workspace.
- NQ, ES and GC are prewarmed by default and retained in server plus browser memory for materially faster instrument switching.
- Previously viewed markets restore immediately from browser memory while the backend synchronizes the selected live market.
- A read-only Cross-Market Radar scans configured markets without changing the active chart or active trade lifecycle.
- Radar candidates must pass deterministic entry validity, model-score, confidence and data-freshness gates.
- Inactive-market alerts are labeled **setup forming**, not executable trades. Opening the market is required before the active engine can validate current GEX, confirmation, entry and risk.
- Radar alerts are recorded in TradeIQ Alerts and can also use browser desktop notifications after explicit permission.
- Databento inactive-market refreshes use incremental one-minute history updates instead of repeatedly downloading the complete history window.


### Self-healing market transport (v3.0.5)

- The Databento live worker recreates the client after an unexpected close instead of terminating permanently.
- A backend watchdog detects a connected stream that has stopped producing records and restarts the active subscription.
- Watchdog recovery is suppressed during the normal CME 5–6 PM ET maintenance break and weekend closure.
- Reconnection performs an incremental historical backfill and merges missing minute bars with verified live overlay bars.
- Instrument switches stop and briefly join the prior live worker before the replacement subscription starts, reducing overlapping clients.
- Market health separately records stream state, data freshness, last record/candle time, retry timing, reconnect counts and the exact disconnect reason.
- The browser WebSocket has a heartbeat watchdog, bounded exponential reconnect and authoritative snapshot resynchronization after recovery.
- WebSocket payload components are isolated: a Claude, GEX, radar or metadata error cannot silently terminate the market update channel.
- The header distinguishes server connectivity from Databento feed health and displays market-data age.

### Time integrity and setup-history display (v3.0.6)

- All persisted setup, lifecycle and alert timestamps are stored and transported as UTC.
- SQLite values that return without `tzinfo` are interpreted as UTC by explicit policy, never as the Railway host time.
- API history/timeline timestamps include an explicit `Z` marker so browsers cannot reinterpret them as local wall-clock values.
- The browser detects its IANA time zone and daylight-saving offset.
- Setup History, lifecycle timeline, alerts, Claude timestamps, radar scans, backtests, chart labels and the header clock use one display-time service.
- Users can choose device-local time or New York exchange time without changing stored data.
- Legacy offset-less TradeIQ timestamps remain readable and are normalized as UTC.

## 5. Entry Models

1. Liquidity Sweep + Structure Shift
2. Supply/Demand Retest
3. OTE Retracement
4. Fib Pullback Continuation
5. Gamma Flip Reclaim
6. Fair Value Gap Retest
7. Order Block Retest
8. EMA Pullback
9. VWAP Reclaim
10. Break & Retest
11. Trend Continuation
12. Inverse FVG
13. SMT Divergence

Each model returns a transparent score, eligibility, trigger, invalidation, evidence and missing data. Unsupported evidence remains missing rather than simulated.

## 6. Confidence

Confidence is deterministic and totals 100 points:

| Category | Maximum |
|---|---:|
| Trend | 20 |
| Structure | 20 |
| GEX | 20 |
| Liquidity | 15 |
| Momentum | 10 |
| Volume | 10 |
| Session | 5 |

The entry model has a separate model score. Monitoring begins when the top eligible model reaches the watch threshold. A limit can arm only after the confidence floor, common risk safety and the selected model's own confirmation groups qualify.

## 7. GEX Policy

Gamma Flip, Call Wall, Put Wall and major nodes remain fixed until the option-position snapshot is refreshed. Fallback GEX remains fixed for the configured refresh window. GEX is contextual and cannot create a trade alone.

## 8. Trade Management

After a locked limit fills:

- Initial stop remains recorded and immutable.
- Active stop begins at the initial stop.
- TP1 secures the configured partial percentage (default 50%).
- The runner stop moves to break-even when enabled.
- TP2 completes the runner.
- MFE and MAE are recorded in points.

## 9. Persistence and Replay

The active lifecycle object survives backend restarts. Every transition is stored with its candle time, price and exact reason. Timeline data supports Claude explanations and setup replay.

## 10. Current Limitations

- No broker order routing.
- Candle-based fill simulation cannot determine intrabar ordering; ambiguous candles are treated conservatively.
- SMT requires synchronized comparison-market data and therefore remains unavailable when that feed is absent.
- Order Block and FVG models use deterministic data already derived by the current structure/zone engine; they are not full depth-of-market models.
- Analytics are descriptive and do not adapt live model weights.
- The Cross-Market Radar monitors NQ, ES and GC for developing candidates, but only the selected instrument owns an executable setup lifecycle.
- Model-specific thresholds are deterministic configuration values and still require live forward testing by symbol/session.
- Clean Chart mode reduces visual noise but does not remove the underlying analytical data or change engine decisions.
- Inactive-market radar GEX may use the stable fallback map until that market becomes active; every alert therefore requires active-market validation.
- Browser notifications depend on user permission and browser/PWA support.
- The radar is an informational scanner and cannot arm, fill, manage or cancel orders on inactive markets.


## 11. Connection and GEX Resilience (v3.0.8)

- The browser WebSocket has an explicit eight-second handshake timeout; a socket may not remain in `CONNECTING` indefinitely.
- When the WebSocket is unavailable, TradeIQ enters a clearly labelled **SERVER REST FALLBACK** mode and polls a lightweight authoritative live-state endpoint every three seconds.
- REST fallback continues updating the newest candle, setup lifecycle, session, feed health and GEX without pretending the WebSocket is connected.
- The full Trade Desk chart and the compact Overview chart use the same fallback state and preserve the selected symbol, timeframe and viewport.
- GEX is available independently of the trade setup lifecycle. Native option positioning is preferred; the session-stable fallback map remains visible while native GEX or the setup engine is warming.
- Fast symbol changes gracefully stop the old Databento session and force-terminate it when necessary before a replacement client starts, preventing overlapping live sessions and connection-limit loops.
- Transport recovery never creates, confirms, fills, cancels or manages a trade. The deterministic engine remains the sole lifecycle authority.

## v3.0.9 Chart Pipeline Integrity

TradeIQ must preserve valid history across genuine session breaks while still rejecting contiguous mixed-contract or corrupt price regimes. Simulated data must never be presented as a live market feed. Temporary live overlays used during reconnection must remain memory-bounded.

## v3.1.0 Adaptive Execution

TradeIQ supports both strong single-model setups and composite institutional confluence clusters. The Decision Brain chooses the stronger valid interpretation, while the Adaptive Execution Engine selects MARKET, LIMIT, STOP, or NONE based on model type, confirmation, freshness, remaining reward, target status, and market-data health.

## v3.1.1 Flexible Institutional Cluster Tiers

TradeIQ accepts either a strong single entry model or a valid composite cluster. The engine does not require a fixed number of confluences and does not automatically prefer a larger label count.

- **Exceptional 2-factor cluster:** allowed only when two independent categories are exceptionally strong, model-native confirmation strength is at least 2, institutional confidence is at least 75%, execution freshness is at least 70%, the structural stop is valid, data is healthy, the target path is clear and at least 2R remains.
- **Standard 3-factor cluster:** normal institutional cluster with at least one model-native confirmation, at least 60% institutional confidence and at least 45% execution freshness.
- **High-priority 4+ factor cluster:** receives the highest composite-selection priority, but still requires model confirmation, a valid structural stop, healthy live data, clear targets and at least 2R.

Related evidence remains grouped: OTE and Fib count as one retracement category; Supply and Order Block do not blindly create two independent categories; sweep, MSS and displacement share the liquidity/structure category. A stronger valid single model may still remain primary when it outranks the composite cluster.

## v3.1.2 Silent Monitoring and Real Entry Publication

TradeIQ may calculate watch triggers, candidate invalidations, model rankings and confirmation windows internally, but no candidate price is published as an entry until the Adaptive Execution Engine returns an executable MARKET, LIMIT or STOP decision.

A retracement limit is valid only when it belongs to a retracement model, is model-confirmed, remains within the real-limit distance envelope, is on the correct resting side of market, retains adequate room before TP1/opposing liquidity, preserves the structural stop and offers at least 2R. Continuation models may use market execution only while the live price remains within tolerance and at least 2R remains from the live price; missed continuations never become distant limits.

Composite clusters inherit execution style from the strongest underlying valid model. The UI and automatic Claude commentary remain silent during internal monitoring and publish only a validated executable plan.
