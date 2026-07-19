# TradeIQ v1.5 — Mobile + iPad Edition

## Added

- Responsive phone and tablet layout connected to the existing TradeIQ backend.
- Mobile bottom navigation: Chart, Setup, Claude, News, and GEX.
- iPad portrait and landscape workspaces.
- Touch-friendly symbol, timeframe, overlay, chart-style, fit, real-time, and fullscreen controls.
- Slide-in navigation drawer for the full desktop page set on smaller devices.
- PWA manifest, service worker, install prompt, app icons, safe-area support, and Add to Home Screen guidance.
- Mobile Finnhub news cards and mobile GEX summary using the active instrument.
- Mobile Analyze Now shortcut that opens the Claude pane.
- Per-device persistence of the selected mobile pane.

## Preserved

- Desktop dashboard and advanced chart workflow.
- NQ, MNQ, ES, MES, GC, and MGC switching.
- Fast-switch candle cache and asynchronous history sync.
- Session gate boundaries: session status does not modify confidence.
- Claude remains read-only and cannot modify engine output.
- Finnhub news remains informational.
- Native/fallback and parent-market GEX labels remain explicit.

## Implementation note

The supplied HTML/CSS concept informed the responsive design. The production package reuses TradeIQ's current Lightweight Charts 5.2 integration and live API/WebSocket data; it does not ship the pasted minified Lightweight Charts 4.2 source or mock data generator.
