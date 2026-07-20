# TradeIQ v3.0.1 — Chart and Candlestick Hotfix

**API version:** `3.0.1-chart-candle-hotfix`

## Problem fixed

On smaller timeframes, candles could become compressed, malformed or visually unstable. The issue came from a combination of distant analytical price lines affecting vertical autoscale and insufficient protection against replayed, duplicated, out-of-order or corrupt live OHLC records.

## Changes

- Candle-only automatic price scaling for the visible chart range.
- Distant GEX, Fib, supply/demand and trade levels no longer flatten 1m/2m candles.
- Stronger Databento live-record validation.
- Out-of-order reconnect records are merged into the correct minute or ignored.
- Historical/live bars are sorted and deduplicated before timeframe aggregation.
- Isolated giant-wick records are removed while legitimate large-bodied repricing is preserved.
- Smaller default visible ranges on 1m/2m, especially on mobile.
- Viewport memory per symbol, timeframe and chart.
- Frontend cache version bumped so browsers and installed PWAs receive the fix.

## Validation

- `108 passed`
- Python compilation passed.
- JavaScript syntax validation passed.
- Live Databento and device-specific visual testing still needs to be performed by the user.
