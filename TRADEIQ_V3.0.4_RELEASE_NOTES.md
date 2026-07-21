# TradeIQ v3.0.4 — Trade Desk and Cross-Market Radar

**API version:** `3.0.4-trade-desk-market-radar`

## Purpose

This release addresses three usability problems: the Claude panel overlapping the setup panel, missing opportunities on ES/GC while watching NQ, and slow instrument switching.

## Changes

### Institutional Trade Desk

- Rebranded the full chart as TradeIQ Desk.
- Renamed navigation to **Overview** and **Trade Desk**.
- Setup, Claude and Market Radar now use separate desktop tabs.
- Only one rail pane is visible at a time.
- The rail can be collapsed for a chart-first workspace.
- The selected tab and rail state persist locally.

### Cross-Market Radar

- Background scanning for NQ, ES and GC.
- Uses the existing deterministic candidate and model-ranking pipeline.
- Requires valid entry structure, minimum model score, minimum confidence and fresh candle data.
- Produces in-app alerts and optional browser notifications.
- Duplicate alerts are suppressed with a configurable cooldown.
- Clicking a radar card opens that market.

Radar alerts are informational. They do not create orders or lifecycle states for inactive markets.

### Faster market switching

- NQ, ES and GC history prewarming is enabled by default.
- Previously viewed markets restore immediately from browser memory.
- Inactive Databento caches receive incremental one-minute updates instead of repeated full-history downloads.
- The authoritative backend snapshot replaces the temporary cache after switching.

### Reliability

- Stale background candles cannot generate an alert.
- WebSocket market updates cannot overwrite the UI during a symbol switch.
- The selector recovers after both successful and failed switches.
- Existing active trade lifecycle logic remains single-market and deterministic.

## New endpoints

```text
GET  /api/multi-market/opportunities
GET  /api/multi-market/status
POST /api/multi-market/scan
```

The manual scan endpoint uses the existing admin protection.

## New configuration

```env
DATABENTO_PREWARM_MARKETS=true
DATABENTO_PREWARM_SYMBOLS=NQ,ES,GC
MULTI_MARKET_ALERTS_ENABLED=true
MULTI_MARKET_SYMBOLS=NQ,ES,GC
MULTI_MARKET_SCAN_SECONDS=45
MULTI_MARKET_HISTORY_REFRESH_SECONDS=60
MULTI_MARKET_MAX_DATA_AGE_SECONDS=180
MULTI_MARKET_MIN_MODEL_SCORE=72
MULTI_MARKET_MIN_CONFIDENCE=45
MULTI_MARKET_ALERT_COOLDOWN_MINUTES=15
```

## Verification

- `126 passed`
- Python compilation passed.
- Frontend JavaScript syntax validation passed.
- ZIP integrity validation passed.

## Not verified here

- Production Databento latency and entitlement behavior.
- Railway deployment.
- Browser/PWA notification delivery on the user's devices.
- Live alert precision or profitability.
