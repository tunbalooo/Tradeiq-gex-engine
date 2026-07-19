# TradeIQ v1.3 — Fast Instrument Switching

## Fixed

- Instrument changes no longer wait for the full Databento historical request before the UI changes.
- First-time markets enter a clearly labelled `DATABENTO SYNC` preview while real history backfills in the background.
- Previously loaded symbols are retained in an in-memory candle cache for fast return switching.
- Finnhub general news is fetched once and filtered locally per market instead of making a new request for every symbol.
- Automatic Claude analysis waits until Databento history is ready.
- TradeIQ cannot arm an order from temporary preview candles; confidence remains unchanged while actionability is gated.
- Preview setups are reevaluated so they can become armable after the market opens or data synchronization finishes.
- Claude is explicitly forbidden from claiming that fallback GEX must become live before an order can be armed. Fallback GEX remains a reliability limitation only.

## Optional

`DATABENTO_PREWARM_MARKETS=true` loads the remaining symbols sequentially after startup. It is disabled by default to avoid unnecessary historical-data usage on every deployment.

## Validation

- 41 automated tests pass.
- Python modules compile successfully.
- Frontend JavaScript syntax checks pass.
