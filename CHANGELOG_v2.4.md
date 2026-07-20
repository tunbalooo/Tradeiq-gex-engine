# TradeIQ v2.4 — Stable Mobile + Clear Execution States

## Mobile chart
- Uses official Lightweight Charts 5.2 on phones and tablets.
- Preserves user zoom and pan during live updates.
- Uses incremental `update()` for realtime bars and guarded `setData()` for history replacement.
- Adds a volume histogram, touch pan/pinch, draggable price scale, and VisualViewport resize handling.
- Distant GEX context no longer expands the mobile candle price range.

## Setup lifecycle
- WATCHING is now displayed as MONITORING ONLY.
- `watch_trigger` is separate from executable `entry`.
- Entry/SL/TP/R:R stay empty until WAITING_FOR_LIMIT.
- An early trigger touch becomes UNCONFIRMED_TOUCH, explicitly recorded as no trade.
- Confirmed WAITING_FOR_LIMIT plans remain locked; a later touch becomes FILLED and retains SL/TP.

## Claude/GEX wording
- Claude is instructed to call fallback values Estimated GEX and never interpret WATCHING as order permission.
