# TradeIQ v1.9 — Mobile Price Navigation + Chart History Guard

## Mobile chart interaction

- Drag left and right anywhere on the chart to move through candle history.
- Drag up and down in the chart body to move the visible price range.
- Drag vertically on the right-hand price scale to compress or expand the price scale.
- Double-tap or use Auto/Fit/Real time to restore automatic price scaling.
- Manual price movement turns Auto off so live refreshes do not snap the chart back immediately.

## Chart history protection

- Candle history is cached independently by symbol and timeframe.
- A one-bar WebSocket refresh is merged into existing history instead of replacing the chart.
- Duplicate timestamps are de-duplicated and incoming bars replace older values at the same timestamp.
- Invalid OHLC bars are rejected before rendering.
- The desktop and mobile chart managers share the same safety principle.

## Unchanged

- Confidence scoring, session gating, Claude permissions, GEX calculations and order arming rules are unchanged.
