# TradeIQ v0.7 — Session Gate

- Added a backend CME Globex session service using America/New_York time.
- Added Asia, London, New York and Globex labels in the dashboard header.
- Added weekend, daily maintenance and scheduled-halt detection with a live countdown.
- Added `/api/session`; session status is also returned by health, dashboard and WebSocket payloads.
- Trade Setup now displays Market Closed, the next open countdown and the current session.
- New setups cannot be armed while the exchange is closed.
- Confidence weights, components and the final confidence score are unchanged.
- Existing filled positions are not altered by the session gate.

Holiday-specific early closes still require an exchange-calendar feed and are not inferred.
