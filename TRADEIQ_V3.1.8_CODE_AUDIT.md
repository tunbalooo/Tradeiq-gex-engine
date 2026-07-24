# TradeIQ v3.1.8 Targeted Code Audit

## Scope

Reviewed the v3.1.7 package paths involved in the reported failures:

- FastAPI startup and routes
- Claude analysis service
- Claude desktop frontend lifecycle
- Cross-market monitor service
- Cross-market radar rendering and notifications
- WebSocket radar transport
- service-worker/static asset caching
- related schemas and regression tests

## Root causes found

### 1. Claude desktop had one transport path

The frontend used EventSource only. A desktop browser, extension, proxy, or hosting layer that buffered/blocked SSE had no alternative transport. The panel could remain blank while the request was unresolved.

### 2. Claude readiness was probed late

`loadClaudeStatus()` ran after market, dashboard, and radar hydration. A preceding startup error could leave the initial `CHECKING` badge unchanged even though the rest of the chart rendered.

### 3. Radar UI confused notification eligibility with setup qualification

The active instrument is intentionally `alertable=false` to prevent duplicate background notifications. The UI used `alertable` to decide whether to reveal direction, model, score, and reason, hiding legitimate active-market candidates.

### 4. Radar did not explain failed gates

The backend returned a generic non-qualified state rather than enumerating exactly which minimum requirements failed.

## Corrections

- Added independent startup status probing and no-cache fetches.
- Added SSE heartbeat/flush, timeout controls, and JSON fallback.
- Shared Claude cache and lock across both transports.
- Added sanitized diagnostic errors and richer status metadata.
- Split radar `qualified` status from `alertable` notification status.
- Added explicit missing-gate calculation and developing states.
- Updated frontend cards to show real model evidence for all developing candidates.
- Hardened radar local-storage persistence against browser storage exceptions.

## Static and automated checks

- `python -m pytest -q`: 199 passed
- `python -m compileall -q backend engine`: passed
- `node --check` on app, boot, time, chart, and service worker: passed
- Direct DOM references checked against HTML IDs: no unresolved references
- Frontend scanned for embedded Anthropic, Databento, and Finnhub secret assignments: none found
- Static asset versions aligned at `v=318`
- API smoke checks completed for health, Claude status/fallback, radar status/opportunities, and GEX summary

## Limits of this audit

- No production Anthropic key, credits, or model permissions were available.
- No live Railway proxy behavior was available for direct browser acceptance testing.
- No production Databento credentials were used.
- This audit does not establish trading profitability or validate model weights.
