# TradeIQ v1.6 — Mobile Chart & News Timestamp Fix

- Fixed blank charts on iPhone and iPad by delaying chart creation until the visible pane has a usable size.
- Replaced chart auto-sizing with explicit ResizeObserver-driven sizing for iOS browser reliability.
- Added chart refreshes for pane changes, page restoration, device rotation, visibility changes, and resize.
- Added a built-in Canvas candlestick fallback if both Lightweight Charts CDN mirrors are unavailable.
- Added a sequential frontend loader so the chart library finishes loading before TradeIQ chart code starts.
- News now displays weekday, calendar date, time, and ET timezone on mobile and desktop.
- Updated the PWA service worker to network-first v1.6 assets so installed devices receive new deployments.
