# TradeIQ v2.3 — Fixed Watch Expiry

## Watch lifecycle

- Watch start and expiry timestamps are immutable after a watch is created.
- Repeated engine refreshes update confidence/context only; they no longer extend the timer.
- At expiry, a watch transitions to `EXPIRED` with outcome `WATCH_EXPIRED`.
- The same expired candidate is suppressed instead of being recreated every cycle.
- A new watch is allowed only after the candidate disappears or materially changes direction, entry, cluster, or zone timeframe.
- Confirmed setups retain the original watch timestamps while receiving a separate locked-limit validity window.

## UI

- Mobile and desktop use `watch_expires_at` while the state is `WATCHING`.
- Expired watches show `WATCH EXPIRED — waiting for a new candidate`.
- Service-worker cache advanced to v2.3.
