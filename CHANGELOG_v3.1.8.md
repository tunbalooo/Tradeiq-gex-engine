# Changelog v3.1.8

- Added `POST /api/ai/analysis` as a non-streaming Claude fallback.
- Added Claude SSE padding and heartbeat to reduce proxy/browser buffering.
- Added frontend SSE first-event and overall timeout watchdogs.
- Added automatic SSE-to-JSON fallback with shared backend lock/cache.
- Moved Claude status probing ahead of market/radar hydration.
- Added bounded status retries and actionable error reporting.
- Added `qualified`, `entry_valid`, `current_price`, and `missing_gates` to radar opportunities.
- Kept active-market qualified setups visible while suppressing duplicate desktop alerts.
- Exposed developing model score/confidence and missing radar gates.
- Added qualified/developing radar counts.
- Updated PWA cache and static asset versions to 318.
