# TradeIQ v3.0.5 — Self-Healing Market Stream

**API version:** `3.0.5-self-healing-market-stream`

## Fixed

- Databento live threads no longer terminate permanently after the client closes or raises an exception.
- Silent streams are detected by a backend watchdog and restarted automatically.
- The old stream is stopped and briefly joined during symbol switching to reduce overlapping NQ/ES/GC subscriptions.
- Missing minute candles are backfilled after reconnection and merged with verified live bars.
- The watchdog recognizes the normal CME maintenance break and weekend closure.
- `/ws/market` isolates optional component failures so one service cannot close the entire market channel.
- The browser closes a silent WebSocket after 12 seconds, reconnects with bounded exponential backoff, checks `/api/health`, and reloads the authoritative candle snapshot.
- The header now separates `SERVER` status, `DATABENTO` status and `DATA AGE`.

## New health fields

- `stream_state`
- `data_fresh`
- `last_record_at` / `last_record_age_seconds`
- `last_candle_at` / `last_candle_age_seconds`
- `reconnect_attempts` / `total_reconnects`
- `next_retry_at`
- `last_disconnect_reason`
- `market_expected_live`

## Validation

- `132 passed`
- Python compilation completed successfully.
- Frontend JavaScript syntax validation completed successfully.
- WebSocket component-isolation test completed successfully.
- Simulated client-recreation and incremental gap-merge tests completed successfully.

This package was not deployed to Railway and was not forward-tested against the user's production Databento entitlement. Live verification is still required.
