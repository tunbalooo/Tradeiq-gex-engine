# TradeIQ v2.5 — Claude lifecycle explanations

- Added deterministic transition metadata to every setup: previous state, next state, reason, time and price.
- Claude receives a dedicated lifecycle event payload and must explain the recorded engine reason.
- Monitoring explanations identify present and missing confirmations before a limit is armed.
- Limit-ready and filled explanations cover locked entry, protective stop, TP1, TP2 and target sources.
- Expired, invalidated, cancelled, early-touch and stopped states explain their exact deterministic cause.
- Frontend queues high-priority lifecycle analysis when a transition occurs during an active Claude stream.
- Updated app version and service-worker cache to v2.5.
