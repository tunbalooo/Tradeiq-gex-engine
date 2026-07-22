# TradeIQ Development Roadmap

**Product version:** 3.0.8-connection-gex-resilience  
**Document version:** 3.0.8  
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


### v3.0.6 — Timezone-Aware Setup History — Released

- [x] Store and transport setup/lifecycle timestamps as explicit UTC.
- [x] Correct legacy SQLite offset-less timestamps.
- [x] Auto-detect browser/device IANA time zone.
- [x] Add local versus exchange-time preference.
- [x] Synchronize Setup History, timeline, alerts, Claude, radar, chart and backtest display times.
- [x] Add regression coverage for UTC serialization and history output.


### v3.0.7 — Model-Native Confirmations — Released

- [x] Assign a deterministic confirmation contract to every entry model.
- [x] Use model-specific confirmation windows.
- [x] Separate structural invalidation from an unconfirmed touch.
- [x] Expose exact missing confirmation conditions to the UI and Claude.

### v3.0.8 — Connection and GEX Resilience — Released

- [x] Add an eight-second WebSocket handshake timeout.
- [x] Add a three-second authoritative REST live-state fallback.
- [x] Keep Overview and Trade Desk charts updating when the socket is unavailable.
- [x] Make GEX summary and chart overlays independent of setup availability.
- [x] Gracefully stop and force-terminate retired Databento sessions before replacement.
- [x] Add regression coverage for fallback transport, independent GEX and session shutdown.

## Next priorities after v3.0.8

- Production observability panel showing WebSocket attempt, REST fallback age, Databento error reason and next retry time.
- Railway log correlation ID for each market connection cycle.
- Live NQ/ES/GC soak test across repeated symbol switches and the CME maintenance window.
- Per-symbol native GEX snapshot cache for instant inactive-market GEX pages.

## Completed in v3.0.9

- [x] Preserve chart history across genuine session gaps.
- [x] Keep contiguous price-regime corruption protection.
- [x] Stop simulated data from appearing live.
- [x] Bound Databento reconnect-overlay memory.

## Released — v3.1.0

- [x] Institutional Confluence Cluster
- [x] Single-model/composite selection
- [x] Adaptive MARKET/LIMIT/STOP/NONE execution
- [x] Execution freshness and distance
- [x] Target-reached-before-fill cancellation
- [x] No-chase departure rule

## Released — v3.1.1

- [x] Allow exceptional two-category institutional clusters.
- [x] Add standard three-factor and high-priority four-plus cluster tiers.
- [x] Prevent related labels from double-counting evidence.
- [x] Add tier-specific confidence, confirmation-strength and freshness gates.
- [x] Compare composite selection strength with the strongest valid single model.
- [x] Fall back to a valid single model when a preferred cluster fails its stricter quality gate.
- [x] Expose cluster tier and active independent categories to the UI and API.
- [x] Add regression coverage for two-, three- and four-plus-factor behavior.

## Released — v3.1.2

- [x] Hide watch/monitor prices from desktop and mobile charts.
- [x] Keep developing direction, confidence and model ranking private until entry publication.
- [x] Add nearby real-limit distance and freshness gates.
- [x] Reject limits too close to TP1/opposing liquidity.
- [x] Prevent continuation models from falling back to distant limits.
- [x] Route composite clusters through the strongest underlying model family.
- [x] Delay automatic Claude commentary until a real plan is published.
- [x] Add regression coverage for silent UI, real limits, fast continuation and cluster execution inheritance.
