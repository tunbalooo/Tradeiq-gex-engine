# TradeIQ v3.0.2 — Entry and Chart Stability

**API version:** `3.0.2-entry-chart-stability`

## Fixed

- Replaced the single universal entry gate with deterministic, model-specific confirmation rules.
- OTE, EMA, VWAP, supply/demand, FVG and continuation setups no longer require the liquidity-sweep sequence belonging to a different entry model.
- The selected entry model can provide its own trigger and structural invalidation to the risk engine.
- Added separate thresholds for monitoring and limit arming.
- Prevented repeated LONG/SHORT setup creation while the engine polls the same closed candle.
- Direction and primary-model changes must persist across distinct closed candles before replacing a watch.
- Setup History now hides transient scanning previews and suppresses near-duplicate lifecycle rows.
- Added Clean Chart mode as the default chart presentation.
- Clean mode limits contextual zones and labels while preserving the nearest institutional levels and every active trade level.
- Improved candlestick body borders and reduced the initial visible-bar count on 1m, 2m and 5m.
- The newest live candle is now sanitized; an isolated malformed latest wick is no longer automatically appended.
- Updated PWA assets and cache version so browsers receive the corrected chart code.

## Safety retained

- TradeIQ does not force an entry merely because a model ranks first.
- A limit still requires a valid resting price, acceptable target space, at least 2R to TP2, the confidence floor, the model score threshold and the model's own confirmations.
- Claude remains read-only.
- Broker execution remains disabled.
