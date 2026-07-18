# TradeIQ v0.4 — Confluence and Trade Lifecycle Update

## Fixed

- Supply and demand now use multi-candle bases, directional displacement, freshness, retest count, strength scoring, and close-based invalidation.
- Liquidity sweeps are direction-specific:
  - Long requires a sell-side sweep.
  - Short requires a buy-side sweep.
- Displacement and FVG checks are direction-specific.
- Added spatial three-way confluence: GEX level + OTE + matching supply/demand zone.
- Limit validation now requires:
  - Buy limit below current price.
  - Sell limit above current price.
- Nearby barriers can block a setup when less than 1R is available.
- Targets now search, in order, across:
  - Call/put walls
  - Strong GEX strikes
  - Previous liquidity
  - Opposing supply/demand zones
  - Session high/low
- The primary target falls back to 2R when no valid market level exists.
- Call wall and put wall are now calculated separately from call and put exposure.
- Gamma flip is estimated by repricing the entire option book over hypothetical NQ prices.

## Added

- `PREVIEW_ONLY` versus actionable `WAITING_FOR_LIMIT` states.
- Frozen entry, SL, TP1 and TP2 after a setup is armed.
- Lifecycle tracking:
  - WAITING_FOR_LIMIT
  - FILLED
  - TP1_HIT
  - TP2_HIT
  - STOPPED
  - INVALIDATED
  - EXPIRED
- Conservative handling when stop and target occur in the same OHLC candle.
- Fixed setup expiry instead of continuously extending expiry.
- `/api/setup/reset` endpoint.
- Target-source labels on the dashboard.
- Cluster score and cluster price area on the dashboard.
- Real performance fields remain zero until actual outcomes are logged; sample profit numbers were removed.

## Important

This update still displays trade plans only. It does not submit orders to a broker.
