# TradeIQ v2.1 — Watching to Locked Limit

## Setup lifecycle

- Adds a stable `WATCHING` setup state for developing long and short candidates.
- Displays `WATCHING LONG @ price` or `WATCHING SHORT @ price` in the chart and Trade Setup panel.
- Shows one fixed amber watch-entry line while confirmation develops.
- The watched entry does not follow every live price update.
- Stop loss, TP1, TP2, risk/reward and the risk box remain hidden while watching.
- When mandatory confirmations pass, the same watched setup becomes `WAITING_FOR_LIMIT`.
- The confirmed limit, SL, TP1, TP2 and risk box then appear and lock.
- If the candidate loses its conditions, changes direction or expires, the watch is removed or replaced.

## Other

- Keeps confidence independent of the session gate.
- Retains the multi-market, mobile navigation, candle-history protection and desktop GEX-by-strike features.
- Updates the API version and web-app cache to v2.1.
