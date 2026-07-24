# TradeIQ v3.1.7 Code Audit

## Scope reviewed

- FastAPI application startup, health, REST and WebSocket routes
- Databento market and option-position services
- GEX calculation, caching and fallback pipeline
- setup construction, confidence, entry models, adaptive execution and trade lifecycle
- storage, scanner/trade history and analytics
- Claude read-only integration boundaries
- frontend state, chart overlays, GEX page, mobile panels and service worker
- Docker, Railway, environment-variable and static-asset configuration
- the complete automated test suite

## Findings fixed in v3.1.7

### 1. GEX analysis did not expose the full option-position landscape

The backend already calculated net GEX by strike, but the UI only showed a basic profile and lacked expiration filtering, open interest, IV and grouped intensity zones. The new radar and typed payload close that gap.

### 2. A single GEX cache could not safely represent multiple expiration views

The native service previously cached one summary per instrument. It now caches separate `0DTE`, `WEEKLY` and `ALL` summaries while retaining one locked option-position snapshot.

### 3. Expiration-day classification could be wrong around the UTC/ET boundary

0DTE and weekly classification now use `RTH_TIMEZONE` and convert expiration timestamps before comparing dates.

### 4. Filtered GEX UI state could be overwritten by live setup updates

A separate `gexViewSummary` now isolates the read-only analysis selection from `setup.gex`, which remains the all-expiration map used by the engine.

### 5. Native GEX was labelled too broadly as estimated

Native open-interest data is now identified as native. The payload separately reports how many IV observations were supplied by the dataset and how many used the deterministic fallback IV curve.

### 6. Stale desktop assets were possible after deployment

The service-worker cache and every static asset query were advanced to v3.1.7.

## Checks completed

- full test suite: 193 passed
- all Python files parsed with `ast` and compiled
- all first-party JavaScript files passed `node --check`
- HTML parsed successfully; no duplicate IDs
- all direct DOM ID references in `app.js` exist in `index.html`
- no TODO/FIXME/HACK markers in production Python/JavaScript
- no obvious hard-coded API key, password or secret assignments
- Docker/Railway commands bind to `0.0.0.0` and `${PORT}`
- admin mutation routes remain token-protected unless explicitly configured public
- Claude remains server-side and read-only
- filtered GEX API accepts only `0DTE`, `WEEKLY` or `ALL`

## Remaining high-value work

### Production-parity backtest

This remains the most important missing component. The current backtest service does not replay the complete live engine, model selection, cluster tiers, adaptive execution, stale-entry cancellation, thesis locks and management logic.

### Dependency reproducibility

`requirements.txt` uses unpinned package names. This is functional but permits upstream updates to alter Railway builds. A tested lockfile should be generated in the deployment environment after live Databento and Anthropic integration tests.

### Live-provider verification

The code paths are covered by mocks and deterministic tests, but final release acceptance should include:

- one native Databento option refresh;
- each available expiration filter;
- one desktop and one mobile browser session;
- one Claude streaming response;
- Railway restart and cache-restoration validation.

### Strategy validation

No code audit can establish edge. Confidence weights, GEX interpretation and execution thresholds must be evaluated out-of-sample over multiple volatility and gamma regimes.
