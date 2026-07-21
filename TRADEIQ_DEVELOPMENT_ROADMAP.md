# TradeIQ Development Roadmap

**Product version:** 3.0.5-self-healing-market-stream  
**Document version:** 3.0.5  
**Status:** Living roadmap

## Released

### v3.0.0 — Institutional Decision Platform

- Decision Brain and deterministic model ranking.
- Weighted confidence engine.
- Stable GEX snapshots.
- Persistent lifecycle, management and analytics.

### v3.0.1 — Chart/Candle Integrity

- Ordered, sanitized candles.
- Small-timeframe autoscale and viewport stability.

### v3.0.2 — Entry/Chart Stability

- Model-specific arming contracts.
- Duplicate setup suppression.
- Clean Chart mode.

### v3.0.3 — Fib Pullback and Realistic Watch Execution

- Fib Pullback Continuation.
- Visible trigger-touch confirmation phase.
- Non-retrospective candle event handling.

### v3.0.4 — Trade Desk and Cross-Market Radar

- Chart-first institutional Trade Desk branding.
- Separate Setup, Claude and Market Radar tabs.
- Collapsible desktop rail; no Claude/setup overlap.
- NQ/ES/GC background scanning and in-app/browser alerts.
- Data-freshness and cooldown protection.
- Browser cache plus Databento prewarming and incremental refresh for faster switching.

## Next priorities

### v3.0.5 — Live validation and observability

- Forward-test NQ, ES and GC radar timing with the production Databento entitlement.
- Add radar latency, cache age and scan-duration metrics.
- Add per-symbol alert enable/disable and session filters.
- Add alert acknowledgement and dismiss controls.
- Measure cold and warm symbol-switch latency.

### v3.1 — Institutional chart workspace

- User-resizable chart/right rail.
- Saved workspace layouts.
- Improved right-axis label collision management.
- Stable crosshair synchronization and drawing persistence.
- Optional detached Claude/Market Radar window.

### v3.2 — Multi-market intelligence

- Synchronized NQ/ES SMT evaluation.
- Cross-asset context such as DXY for GC.
- Portfolio-level opportunity priority and conflict control.
- Native per-market GEX snapshot caching for inactive markets.

### v3.3 — Execution analytics

- Radar-to-watch conversion rate.
- Alert precision by market/model/session.
- Missed-entry and cancellation analytics.
- Historical replay of radar detection through trade completion.

## Safety backlog

- Broker order routing remains out of scope until simulation, replay and live paper testing are validated.
- Claude remains read-only.
- An inactive-market radar card never becomes an order without active-market deterministic confirmation.


### v3.0.5 — Self-Healing Market Stream — Released

- [x] Recreate the Databento client after unexpected closure.
- [x] Detect silent/stale live streams with a backend watchdog.
- [x] Respect CME maintenance and weekend closures.
- [x] Backfill missing candles after reconnect.
- [x] Add browser WebSocket heartbeat and bounded backoff.
- [x] Prevent optional payload-component failures from closing `/ws/market`.
- [x] Separate server status, feed status and data age in the header.
- [x] Add regression coverage for stale detection, client recreation, gap merge and WebSocket isolation.
