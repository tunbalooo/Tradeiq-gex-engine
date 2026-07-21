# TradeIQ v3.0.2 — Entry and Chart Stability

**API version:** `3.0.2-entry-chart-stability`

## Why this update was required

The v3.0 Decision Brain ranked several entry models, but the setup service still applied one universal liquidity/cluster gate to all of them. This meant an OTE, EMA, VWAP or zone-retest model could rank first and still never arm unless it also satisfied the rules of the Liquidity Sweep model. The two-second engine loop could also create repeated alternating watches from the same closed candle, filling Setup History with transient rows.

The chart itself was receiving valid candles, but too many zones and right-axis labels made the candlesticks difficult to read. The latest live candle also bypassed the final malformed-wick check.

## Entry engine changes

- Each model now owns a deterministic confirmation contract.
- The primary model supplies its preferred entry trigger and structural invalidation when available.
- Monitoring begins from model quality instead of waiting for the former 75-point global gate.
- A locked limit requires:
  - valid resting entry;
  - no nearby target blockage;
  - TP2 of at least 2R;
  - institutional confidence of at least 45;
  - primary model score of at least 72;
  - all confirmation groups for that model.
- A ranked model below the arm threshold can remain in WATCHING rather than disappearing.

## Lifecycle stability

- Replacement direction/model evidence is counted only once per distinct closed candle.
- The default replacement requirement is two closed candles.
- Repeated API/engine polling of the same candle cannot produce new setup rows.
- Meaningful cancellation reasons are recorded as `INVALIDATED`.
- Transient `PREVIEW_ONLY` scans are hidden from Setup History.

## Chart clarity

Clean Chart mode is enabled by default. It keeps:

- candles and volume;
- EMA structure;
- Gamma Flip, Call Wall, Put Wall and Max Pain;
- the nearest demand and supply zones plus the selected zone;
- the principal OTE levels;
- VWAP;
- every watching or locked trade level.

It suppresses extra GEX nodes, duplicate right-axis labels, secondary VWAP bands and distant zones. Users can disable Clean mode to restore the full analytical map.

## Validation

The local package passed:

- `114` pytest tests;
- Python compilation;
- JavaScript syntax checks;
- ZIP integrity verification.

This validation did not include the user's live Databento entitlement, Railway environment, installed PWA cache, broker execution or device-specific interaction testing.
