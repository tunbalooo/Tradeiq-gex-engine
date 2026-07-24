# TradeIQ v3.1.7 — Full GEX Radar & Code Integrity Audit

API version: `3.1.7-gex-radar-code-audit`

## What changed

### Full strike-by-strike GEX radar

The GEX Analysis workspace now renders a horizontal gamma profile aligned by strike. Positive net GEX extends to the right and negative net GEX extends to the left. The radar overlays:

- current futures price (Spot);
- Gamma Flip;
- Max Pain;
- Call Wall;
- Put Wall;
- high-concentration positive and negative GEX zones.

### Expiration views

The read-only GEX analysis endpoint now supports:

- `0DTE` — contracts expiring on the current exchange date;
- `WEEKLY` — contracts expiring within seven calendar days, including 0DTE;
- `ALL` — every eligible expiration currently loaded by the native GEX service.

The active trade engine continues to use the locked `ALL` map. Selecting another view changes only the GEX Analysis display and cannot modify an active setup, score, entry, stop or target.

### Strike metadata

Each strike now carries:

- call GEX;
- put GEX;
- net GEX;
- call open interest;
- put open interest;
- total open interest;
- open-interest-weighted implied volatility;
- number of expirations contributing to the strike.

The page includes a Top Gamma Nodes table and hover details on the radar.

### GEX intensity zones

Adjacent high-exposure strikes with the same sign are grouped into zones. The strongest zones are:

- listed in the GEX Analysis page;
- shaded on the GEX radar;
- projected onto the main trading chart when the GEX overlay is enabled.

A GEX zone remains context, not an automatic entry. The deterministic setup and execution gates are unchanged.

### Source-quality clarity

Native Databento option positioning is no longer labelled as a fallback estimate merely because some contracts required model-estimated implied volatility. The payload reports observed and estimated IV contract counts and displays a calculation note.

## Code-integrity corrections

- Expiration filtering uses the configured exchange timezone rather than UTC calendar boundaries.
- Filtered GEX cache entries are isolated by expiration view.
- Filtered mobile/desktop GEX state is isolated from the live all-expiration trade-engine state.
- Symbol changes clear the prior market's filtered GEX view.
- Service-worker and frontend asset versions were advanced to prevent stale desktop bundles.
- API validation rejects unsupported expiration modes.

## Verification

- `193 passed`
- Python AST parsing and compilation passed for `backend`, `engine` and `tests`.
- JavaScript syntax passed for `app.js`, `trading_chart.js`, `boot.js`, `time.js` and `service-worker.js`.
- HTML IDs are unique and every direct `$("id")` reference resolves to an element.
- `git diff --check` passed.
- ZIP extraction/integrity and SHA-256 verification passed.

## Not proven by this release

- The strategy weights and thresholds are not proven profitable.
- The simplified historical backtester is not yet production-parity with the live decision engine.
- Live Databento and Anthropic calls were not executed in the packaging environment because production credentials were not available.
- GEX uses a deterministic call-positive/put-negative dealer-position assumption; it is an analytical model, not an observed dealer inventory feed.
