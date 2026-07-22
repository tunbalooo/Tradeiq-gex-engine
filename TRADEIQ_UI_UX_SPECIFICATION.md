# TradeIQ UI/UX Specification

**Version:** 3.0.8

## Design Language

- Dark institutional interface.
- Information-dense desktop layout.
- Touch-first mobile chart workspace.
- Minimal animation and no decorative AI widgets.
- Color is reserved for state, risk and direction.

## Setup Panel

Always show:

- Lifecycle status
- Direction
- Primary model and score
- Up to three backup models
- Confidence and grade
- Reason/missing confirmations through Claude
- Watch phase and exact next required event

Show only after `WAITING_FOR_LIMIT`:

- Locked entry
- Initial stop
- Active stop
- TP1 and source
- TP2 and source
- Risk/reward
- Risk/reward boxes

## Model Ranking

Display the five highest models. Clearly distinguish:

- Primary qualified model
- Qualified backups
- Developing/ineligible models and missing evidence

## Chart

### Default Clean Mode

Clean mode is enabled on first load. It keeps the core candle/EMA/trade view and only the nearest or selected institutional context. The user can turn Clean off to reveal the complete analytical map. Clean mode changes presentation only; it never changes scoring or trade state.


- Watch trigger: dashed amber line with `NO ORDER` language.
- After price touches the watch line, change its label to `TOUCHED · CONFIRM LONG/SHORT` without drawing a fill or risk plan.
- The setup panel must show `Watch Touched · Awaiting Confirmation`, the deadline and the structural invalidation.
- Locked entry: fixed limit line.
- Initial stop: fixed red line and fixed risk box.
- Active stop after TP1: separate amber break-even line.
- Targets remain fixed.
- GEX levels remain stable until refresh.
- Automatic vertical scaling follows visible candle OHLC only; off-screen GEX/Fib/zone/target levels must not flatten candles.
- 1m/2m defaults show fewer bars so candle bodies remain readable.
- Symbol/timeframe viewports are remembered independently.
- Invalid, duplicated or out-of-order bars must never be rendered.
- The latest live bar must pass the same malformed-wick test as historical bars.
- Duplicate right-axis tags are suppressed while their underlying lines remain visible.
- Default 1m/2m/5m visible ranges must preserve readable candle bodies.
- Fib Pullback Continuation clean mode shows only its 50%, 61.8% and shaded continuation band; it must not add duplicate OTE labels.


## Watch-State Language

The UI must distinguish location, confirmation and execution:

- `MONITORING LONG/SHORT`: price has not reached the watch trigger.
- `CONFIRMING LONG/SHORT`: price reached the trigger; no order is active.
- `WAITING_FOR_LIMIT`: the deterministic plan is armed and all levels are locked.
- `FILLED` / `TP1_HIT`: an actual managed position exists.
- `UNCONFIRMED_TOUCH`: the trigger was reached but confirmation expired; no order existed.

The UI must never use words such as “filled,” “active trade” or “risk remaining” during `WATCHING`.

## Mobile

- Mobile is a purpose-built chart workspace, not a shrunken desktop.
- Maintain one-finger pan, pinch zoom, stable history, fullscreen and crosshair behavior.
- Setup, Claude, News and GEX use dedicated mobile panes.

## History and Analytics

Setup History includes model, grade, initial/active stop, management state and result. Transient preview/scanning rows are hidden, and repeated rows from the same closed candle are suppressed. Model analytics are explicitly read-only.

## Desktop Trade Desk (v3.0.4)

The full-chart workspace is the primary execution surface and is branded **TradeIQ Desk**.

### Right rail

- Tabs: **Setup**, **Claude**, **Market Radar**.
- Exactly one tab is visible at a time on desktop.
- Every pane scrolls independently inside the rail.
- Claude can never sit underneath or overlap the setup panel.
- The Desk button and close control collapse the entire rail; chart resize is triggered immediately.
- The last selected tab and collapsed state persist in local storage.

### Market Radar

Each card shows:

- symbol and direction;
- selected entry model;
- model score;
- watch price;
- confidence grade;
- deterministic reason;
- whether the item is alertable.

Selecting a card switches the active instrument. Alerts must say **setup forming** and must not imply an order exists.

### Market switching

- The current symbol is saved to browser memory before switching.
- A previously viewed symbol paints immediately from browser memory.
- The server response then replaces cached content with authoritative candles, setup, session and instrument metadata.
- NQ, ES and GC are server-prewarmed by default.
- The selector shows a busy state and is always restored after success or failure.

### Navigation branding

- `Overview` replaces the generic Dashboard label.
- `Trade Desk` replaces the generic Chart label.
- The chart header identifies the active instrument and TradeIQ Desk.

## Mobile behavior

The existing bottom navigation remains the mobile control surface. Desktop tabs are hidden on small screens so the current mobile Setup/Claude/News pane system remains touch friendly and does not duplicate controls.


## Connection and Feed Health (v3.0.5)

The top bar must never combine browser/server connectivity with market-feed health. It displays three independent facts:

- `SERVER LIVE` or `SERVER RECONNECTING` for the browser WebSocket.
- `DATABENTO LIVE`, `SYNC`, `RECONNECTING`, `STALE`, `DEGRADED`, or `MARKET CLOSED` for the backend feed.
- `DATA <age>` showing how long ago the latest live market record was received.

A stale or reconnecting feed uses amber/red state styling while the last valid candles remain visible. Recovery must not reset the chart viewport. After the socket or feed returns, the client reloads the authoritative candle snapshot and preserves the user's symbol/timeframe view.


## Time and Setup History (v3.0.6)

- Setup History displays the detected IANA zone and current abbreviation.
- Every history row uses a UTC source timestamp converted with the browser's daylight-saving rules.
- The user can select **Auto-detect this device** or **Exchange time (New York)** in Settings.
- The chart, header clock, lifecycle timeline, alerts, Claude timestamps, radar scans and backtest rows use the same display-time preference.
- Existing offset-less history values are treated as UTC to prevent a four- or five-hour shift.
- A visible zone suffix such as `EDT`, `EST` or `GMT` accompanies setup-history timestamps.


## Connection Fallback and GEX Availability (v3.0.8)

The header presents one of three truthful server transport states:

- `SERVER LIVE` — WebSocket updates are active.
- `SERVER REST FALLBACK` — WebSocket is unavailable, but live-state polling is maintaining the chart and panels.
- `SERVER RECONNECTING` — neither transport has produced a current response yet.

The Databento badge and data-age badge remain separate. REST fallback must update both the Overview chart and the full Trade Desk chart without resetting zoom or pan.

The GEX Analysis page must render from the latest independent GEX summary even when the current setup is unavailable. GEX overlays remain available on the chart during setup-engine warmup. A short syncing explanation replaces an empty page when no market price exists yet.

## v3.0.9 Feed truth and chart continuity

The chart may show a price gap across a valid session break without deleting the earlier session. The header must label local generated data as `SIMULATED`; only verified Databento records may display a live/fresh state.

## v3.1.0 Execution Display

The setup card displays the chosen execution type, freshness percentage, distance from ideal entry, and institutional cluster score. Labels distinguish Market Entry, Limit Entry, Stop Entry, and No Entry. Missed setups explicitly state that analysis was correct but no chase is allowed.

## v3.1.1 Cluster Tier Display

The Setup card, Trade Desk rail and Confluence page display the composite tier explicitly:

- `EXCEPTIONAL 2-FACTOR CLUSTER`
- `STANDARD 3-FACTOR CLUSTER`
- `HIGH-PRIORITY 4-FACTOR CLUSTER` or the actual larger category count

The interface also displays the composite score and independent active categories. When a cluster is recognized but its stricter execution-quality gate is incomplete, the explanation states that TradeIQ selected the valid stronger single model instead. Cluster eligibility never implies that an order was filled.

## v3.1.2 Silent Pre-Entry Interface

Before a plan is locked, desktop and mobile display `SCANNING QUIETLY` and no entry, stop, targets, direction, grade, cluster price or developing model ranking. Internal watch triggers are not drawn and do not affect chart autoscaling. Market Radar displays `SCANNING` without a candidate watch price.

After an executable plan is locked, the interface publishes only the exact MARKET, LIMIT or STOP entry, structural stop, TP1, TP2, risk/reward, model and confluence explanation. Automatic Claude analysis starts only for published or previously armed lifecycles; manual Analyze remains available.

## v3.1.3 Clean Institutional Map

Clean chart mode replaces the raw GEX/Fib/zone/VWAP line stack with the active actionable cluster and nearest opposing liquidity. When no cluster is actionable, only nearest support and resistance are shown. Cluster bands remain contextual and must not use entry language. The Confluence page may show the full compact ladder and contributors. Locked MARKET/LIMIT/STOP, SL, TP1 and TP2 retain visual priority.

