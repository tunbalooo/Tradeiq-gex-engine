# Changelog v3.0.8

- Added `/api/live-state` REST transport fallback.
- Added WebSocket connection-handshake timeout.
- Added independent `/api/gex/summary` fallback behavior.
- Added `gex_summary` to the WebSocket payload.
- Preserved GEX overlays during setup warmup.
- Added `SERVER REST FALLBACK` UI state.
- Added forced Databento session termination before replacement.
- Increased `DATABENTO_STOP_JOIN_SECONDS` default from 2 to 6.
- Added v3.0.8 regression tests.
