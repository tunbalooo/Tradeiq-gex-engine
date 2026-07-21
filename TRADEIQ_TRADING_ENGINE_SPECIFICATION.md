# TradeIQ Trading Engine Specification

**Version:** 3.0.3

## Deterministic Pipeline

1. Load sufficient historical candles before live evaluation and identify the newest completed and live execution candles.
2. Calculate 5m/15m/1H structure and zones.
3. Load a stable GEX snapshot.
4. Calculate OTE, VWAP, volume and session evidence.
5. Build a preliminary protected entry/stop/target proposal.
6. Calculate institutional confidence.
7. Rank all entry models.
8. Rebuild the plan from the selected model trigger and structural invalidation when supplied.
9. Apply common risk safety plus that model's confirmation contract.
10. Use completed candles for confirmation and the live candle for watch touches, fills, stops and targets.
11. Transition the persistent setup lifecycle.
12. Queue Claude explanation for the recorded transition.


## Model-Specific Arming Contract

The Decision Brain must not use one strategy's confirmation rules as a universal gate. Every supported model defines required OR-groups. Examples:

- **Liquidity Sweep + MSS:** liquidity sweep, displacement and ordered sequence.
- **OTE Retracement:** OTE overlap, trend alignment, zone/GEX support, and displacement or sequence.
- **EMA Pullback:** trend alignment, VWAP alignment, and displacement or volume expansion.
- **VWAP Reclaim:** VWAP alignment, trend alignment and displacement.
- **FVG Retest:** directional FVG, displacement and trend alignment.
- **Fib Pullback Continuation:** 50%–61.8% zone touch, completed rejection/reclaim, fresh body-midpoint entry and trend alignment.

Common safety remains mandatory for every model: valid resting entry, unblocked target path, TP2 of at least 2R and the institutional confidence floor.

Default deterministic thresholds:

- Watch model score: 58
- Limit-arm model score: 72
- Institutional confidence floor: 45
- Replacement confirmation: 2 distinct closed candles
- Watch-touch confirmation window: 5 minutes

## State Rules

### PREVIEW_ONLY

No executable plan. Entry, stop and targets are hidden.

### WATCHING

A monitoring trigger exists. It is not an order. A stronger qualified secondary model can replace the primary model and trigger while retaining the lifecycle history, but only after the replacement persists across the configured number of distinct closed candles.

When the live market trades through the watch trigger, the order state remains `WATCHING` and the watch phase changes to `TRIGGER_TOUCHED`. The visible status becomes `CONFIRMING_LONG` or `CONFIRMING_SHORT`. No entry, fill, stop, target or risk box exists yet. A finite confirmation deadline starts from the touch event.

The next deterministic outcome is one of:

- model confirmation → `WAITING_FOR_LIMIT`;
- structural failure → `INVALIDATED`;
- deadline without confirmation → `UNCONFIRMED_TOUCH`;
- stable stronger model → `WATCHING → WATCHING` model switch.

### WAITING_FOR_LIMIT

The entry, initial stop, TP1 and TP2 are locked. Context refreshes cannot move them. A fill is checked from the newest live candle before fresh context can cancel the resting plan.

### FILLED

The locked entry traded. The active stop begins at the initial stop.

### TP1_HIT

The configured partial is secured. The runner remains active. If enabled, the active stop advances to the locked entry.

### TP2_HIT

The runner target is complete.

### STOPPED

The active stop traded. `BREAKEVEN_AFTER_TP1` records partial profit followed by a break-even runner exit.

## Conservative OHLC and Event-Sequencing Rules

- Entry and stop in the same candle: stop-first when event order cannot be established.
- Active stop and TP2 in the same candle: stop-first when event order cannot be established.
- No fill is recorded from a watch trigger.
- A plan cannot arm after its original watch expiry.
- The live candle range already present when monitoring begins cannot retrospectively touch the watch line.
- The live candle range already present when a plan is armed cannot retrospectively fill the order.
- Incremental observation snapshots still detect a new same-candle crossing after monitoring or arming.
- On a fill candle, earlier high/low extremes are not treated as post-fill events.
- On the candle that activates a break-even stop after TP1, earlier extremes are not treated as post-activation stop hits.



## Fib Pullback Continuation Contract

### Bullish

1. Detect a directional bullish impulse and valid swing range.
2. Calculate the pullback band from 50% to 61.8% of the impulse.
3. Monitor the band midpoint; this is not an order.
4. Require a completed bullish candle that interacts with and reclaims the band with sufficient body/rejection quality.
5. Place the resting buy limit at the 50% body midpoint of that confirmation candle.
6. Put structural invalidation below the pullback extreme/band with an ATR/tick buffer.
7. Reject stale confirmation when price has moved too far beyond the proposed limit.

### Bearish

Apply the symmetric rules: premium retracement, bearish rejection/reclaim, body-midpoint sell limit and invalidation above the pullback structure.

The model is rejected when the impulse is weak, the trend is misaligned, the swing is invalid, the confirmation is stale, common risk safety fails or the target path cannot produce at least 2R.

## Model Ranking Contract

Every model returns:

- key
- name
- direction
- score 0–100
- eligibility
- priority
- trigger price
- invalidation price
- supporting reasons
- missing confirmations

## Claude Contract

Claude receives the current setup, latest transition, recent timeline, primary model, model score, backup models, management state and exact recorded reason. It is prohibited from modifying them.

## Setup History Policy

Transient scanning previews are not trade-history records. The history endpoint hides `PREVIEW_ONLY` rows that never became a watch and suppresses near-duplicate lifecycle rows. Full deterministic transitions remain available in each setup timeline.
