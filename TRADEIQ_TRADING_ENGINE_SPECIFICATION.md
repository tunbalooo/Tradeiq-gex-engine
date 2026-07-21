# TradeIQ Trading Engine Specification

**Version:** 3.0.2

## Deterministic Pipeline

1. Load sufficient historical candles before live evaluation.
2. Calculate 5m/15m/1H structure and zones.
3. Load a stable GEX snapshot.
4. Calculate OTE, VWAP, volume and session evidence.
5. Build a preliminary protected entry/stop/target proposal.
6. Calculate institutional confidence.
7. Rank all entry models.
8. Rebuild the plan from the selected model trigger and structural invalidation when supplied.
9. Apply common risk safety plus that model's confirmation contract.
10. Transition the persistent setup lifecycle.
11. Queue Claude explanation for the recorded transition.


## Model-Specific Arming Contract

The Decision Brain must not use one strategy's confirmation rules as a universal gate. Every supported model defines required OR-groups. Examples:

- **Liquidity Sweep + MSS:** liquidity sweep, displacement and ordered sequence.
- **OTE Retracement:** OTE overlap, trend alignment, zone/GEX support, and displacement or sequence.
- **EMA Pullback:** trend alignment, VWAP alignment, and displacement or volume expansion.
- **VWAP Reclaim:** VWAP alignment, trend alignment and displacement.
- **FVG Retest:** directional FVG, displacement and trend alignment.

Common safety remains mandatory for every model: valid resting entry, unblocked target path, TP2 of at least 2R and the institutional confidence floor.

Default deterministic thresholds:

- Watch model score: 58
- Limit-arm model score: 72
- Institutional confidence floor: 45
- Replacement confirmation: 2 distinct closed candles

## State Rules

### PREVIEW_ONLY

No executable plan. Entry, stop and targets are hidden.

### WATCHING

A monitoring trigger exists. It is not an order. A stronger qualified secondary model can replace the primary model and trigger while retaining the lifecycle history, but only after the replacement persists across the configured number of distinct closed candles.

### WAITING_FOR_LIMIT

The entry, initial stop, TP1 and TP2 are locked. Context refreshes cannot move them. A fill is checked before cancellation on each closed candle.

### FILLED

The locked entry traded. The active stop begins at the initial stop.

### TP1_HIT

The configured partial is secured. The runner remains active. If enabled, the active stop advances to the locked entry.

### TP2_HIT

The runner target is complete.

### STOPPED

The active stop traded. `BREAKEVEN_AFTER_TP1` records partial profit followed by a break-even runner exit.

## Conservative OHLC Rules

- Entry and stop in the same candle: stop-first.
- Active stop and TP2 in the same candle: stop-first.
- No fill is recorded from a watch trigger.
- A plan cannot arm after its original watch expiry.

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
