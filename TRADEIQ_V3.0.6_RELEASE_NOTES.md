# TradeIQ v3.0.6 — Timezone-Aware Setup History

**API version:** `3.0.6-timezone-aware-history`

## Fixed

- Setup History no longer treats UTC database timestamps as browser-local time.
- SQLite timestamps without an offset are explicitly interpreted as UTC.
- Setup-history and lifecycle API responses now carry an explicit `Z` UTC marker.
- The browser detects its IANA time zone automatically and applies daylight-saving rules.
- Setup History shows the active zone and abbreviation beside every timestamp.
- Alerts, lifecycle timeline, Claude timestamps, backtests, market-radar scans and chart time labels use the same display-time service.
- A Settings control allows switching between device-local time and New York exchange time.
- The top clock identifies the actual active time-zone abbreviation instead of always claiming `ET`.

## Time policy

TradeIQ stores and transports timestamps in UTC. Conversion happens only in the UI. Legacy offset-less timestamps are treated as UTC because that is how previous TradeIQ releases persisted them.

## Validation

- `135 passed`
- Python compilation passed.
- Frontend JavaScript syntax validation passed.
- Package excludes `.env`, databases, Python caches and test caches.

Live Railway/PWA validation is still required after deployment.
