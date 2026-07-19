# TradeIQ v1.8 — Clean Mobile + GEX by Strike

## Fixed

- Removed the persistent blank mobile chart failure by routing phone/tablet chart rendering through a native Canvas engine.
- Removed the mobile chart's dependency on successful Lightweight Charts CDN initialization.
- Reset mobile chart position when changing symbol or timeframe.
- Added functional mobile zoom, pan, recenter, fit, candle/line, drag, and fullscreen controls.

## Mobile redesign

- Rebuilt the chart screen around a standard trading-terminal layout.
- Reduced decorative gradients, oversized controls, card clutter, and AI-styled visual treatments.
- Added a compact chart footer for Indicators, Draw, and Full screen.
- Changed the mobile Claude navigation label to Assistant while preserving the same read-only Claude integration.
- Split News into Economic Calendar and Headlines tabs.
- Grouped upcoming events by scheduled day/date with ET time, impact, forecast, and previous values.
- Rebuilt headline rows with publication date/time and source in a standard list.
- Added a mobile GEX-by-strike chart.

## Desktop GEX

- Added a full-width GEX Exposure by Strike panel to the desktop GEX Analysis page.
- Added positive/negative exposure bars and a gamma-flip marker.
- Added native/estimated source labeling.

## Backend

- Added `GexStrike` schema.
- Added `gex.by_strike[]` with strike, call GEX, put GEX, and net GEX.

## Safety

- No changes to confidence scoring.
- No changes to session gating.
- No changes to setup arming or order lifecycle.
- No changes to Claude permissions.
