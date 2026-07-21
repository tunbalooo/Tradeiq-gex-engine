# TradeIQ v3.0.8 — Connection and GEX Resilience

## Purpose

This release addresses the failure mode where the header remained on **SERVER RECONNECTING**, the full Trade Desk chart stopped updating, and the GEX Analysis page appeared unavailable even though the REST API and previously loaded candles were still accessible.

## Changes

### WebSocket recovery

- Added an eight-second WebSocket handshake timeout.
- A browser socket can no longer remain indefinitely in the `CONNECTING` state.
- Reconnect attempts retain bounded exponential backoff.

### REST live fallback

- Added `GET /api/live-state` as a lightweight authoritative mirror of the live market payload.
- While the WebSocket is unavailable, the browser polls this endpoint every three seconds.
- The newest candle, setup, session, feed health and GEX continue updating.
- The header shows **SERVER REST FALLBACK** rather than falsely claiming the WebSocket is live.
- WebSocket recovery automatically disables fallback polling and resynchronizes history.

### Independent GEX availability

- `GET /api/gex/summary` no longer depends exclusively on an active setup.
- Native GEX is preferred; the existing session-stable fallback map is used while native options positioning or the setup engine is warming.
- GEX overlays remain available on both charts during setup warmup.
- The GEX Analysis page now refreshes independently and no longer renders as an empty page solely because the setup object is unavailable.

### Databento session retirement

- Symbol changes and stream restarts now attempt a graceful `Live.stop()` first.
- If the retired worker remains open, TradeIQ force-terminates the old Databento session before starting its replacement.
- The default stop/join allowance is increased to six seconds.
- This reduces overlapping live sessions and connection-limit retry loops after repeated NQ/ES/GC switching.

## Validation

- 143 automated tests passed.
- Python compilation passed.
- Frontend JavaScript syntax validation passed.
- REST live-state, independent GEX, WebSocket GEX payload and forced session termination received regression coverage.

## Limitations

This release was not connected to the user's production Railway service or Databento entitlement. Live production testing is still required. REST fallback keeps the interface current only when the backend itself is reachable; it cannot create data when Databento is rejecting the API key, subscription, symbol or account entitlement.
