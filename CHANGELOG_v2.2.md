# TradeIQ v2.2 — Stable Chart Core

## Chart data integrity

- Removed simulated preview candles from the live Databento service.
- Added OHLC validation, timestamp deduplication and isolated-spike filtering.
- Added an 8% history/live price-regime continuity gate.
- Mixed contract or provenance data is rejected instead of stitched together.
- Live-only bars remain visible while coherent historical data is refreshed.
- `/api/market/snapshot` now returns history readiness, source, raw contract and quality metadata.
- WebSocket updates remain connected even when no complete setup or candle history is available.

## Desktop and mobile charting

- Added a visible data-sync / regime-reset banner.
- Added iPhone pseudo-fullscreen fallback when native fullscreen is unavailable.
- Preserved two-axis mobile drag, right-price-scale zoom, pinch, pan, fit and real-time recentering.
- Indicators and trade overlays stay hidden when no coherent setup/history is available.

## GEX reference levels

- Added Gamma Resistance / Call Wall presentation.
- Added Put Support / Put Wall presentation.
- Added Maximum Pain from actual option open interest.
- Added RTH Equilibrium to chart reference levels.
- Preserved Gamma Flip and ranked Strong +GEX / Strong -GEX levels.
- Maximum Pain remains unavailable for net-GEX-only fallback data rather than being estimated without OI.

## Tests

- 82 tests passed.
