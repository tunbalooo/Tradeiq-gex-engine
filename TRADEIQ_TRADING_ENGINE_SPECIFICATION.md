# TradeIQ Trading Engine Specification

**Version:** 3.0

## Deterministic Pipeline

1. Load sufficient historical candles before live evaluation.
2. Calculate 5m/15m/1H structure and zones.
3. Load a stable GEX snapshot.
4. Calculate OTE, VWAP, volume and session evidence.
5. Build a protected entry/stop/target proposal.
6. Calculate institutional confidence.
7. Rank all entry models.
8. Apply the model-score and mandatory safety gates.
9. Transition the persistent setup lifecycle.
10. Queue Claude explanation for the recorded transition.

## State Rules

### PREVIEW_ONLY

No executable plan. Entry, stop and targets are hidden.

### WATCHING

A monitoring trigger exists. It is not an order. A stronger qualified secondary model can replace the primary model and trigger while retaining the lifecycle history.

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
