# TradeIQ v2.8 — Stable GEX Intelligence

## Added

- GEX maps are locked to the current option-position snapshot.
- Gamma Flip, Call Wall, Put Wall and major nodes no longer re-center on every futures tick.
- Fallback GEX is cached for the configured GEX refresh window.
- Manual GEX refresh clears the fallback cache when native Databento positions are unavailable.
- Dealer-bias interpretation, positive/negative gamma balance, top gamma nodes and level meanings.
- GEX health now reports whether levels are locked and the reference price used.

## Safety

GEX remains contextual evidence. Estimated GEX is clearly marked and does not independently create a trade.
