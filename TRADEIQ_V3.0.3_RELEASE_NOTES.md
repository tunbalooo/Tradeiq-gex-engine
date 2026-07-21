# TradeIQ v3.0.3 — Fib Pullback and Watch Execution

**API version:** `3.0.3-fib-pullback-watch-execution`

## Why this update was required

A monitoring line previously behaved like a passive annotation. Price could trade through the line while the setup panel continued to say `WATCHING`, giving no immediate indication that the trigger had been reached. The old behavior also treated an unconfirmed touch as terminal too quickly, which was not realistic for a trader waiting for a rejection or displacement candle.

This release gives the watch line a visible, deterministic lifecycle and adds a separate confirmed Fibonacci continuation model.

## Fib Pullback Continuation

TradeIQ now ranks **Fib Pullback Continuation** independently from the anticipatory OTE model.

For a bullish model:

1. A valid bullish impulse defines the swing.
2. TradeIQ monitors the 50%–61.8% retracement zone.
3. Price must interact with that zone.
4. A completed execution candle must reclaim/reject the zone in the bullish direction.
5. The locked buy limit is placed at the 50% body retracement of the confirmation candle.
6. The stop is placed beyond the pullback's structural invalidation, not at a fixed Fibonacci percentage.

The bearish model applies the symmetric rules.

The model remains in monitoring mode when only the location is valid. It cannot arm until touch, rejection, trend alignment, entry freshness and common risk controls qualify.

## Watch-line execution lifecycle

A watch trigger is still **not an order**, but touching it now produces an immediate visible event:

`WATCHING → CONFIRMING_LONG/CONFIRMING_SHORT`

The setup retains `order_state=WATCHING` while `watch_phase=TRIGGER_TOUCHED`. The UI and chart show that price reached the trigger and that no fill has occurred.

TradeIQ then opens a finite confirmation window:

- If the selected model confirms, the engine locks Entry, SL, TP1 and TP2 and transitions to `WAITING_FOR_LIMIT`.
- If structural invalidation trades first, the setup transitions to `INVALIDATED` with the exact level and reason.
- If confirmation does not complete before the deadline, the setup transitions to `UNCONFIRMED_TOUCH` and records that no order was armed.
- A stronger model may replace the watch only after its evidence persists across distinct closed candles.

The default confirmation window is five minutes and can be configured with:

```env
WATCH_CONFIRMATION_MINUTES=5
```

## Closed-candle confirmation and live-price execution

- Completed candles drive deterministic model confirmation.
- The newest live candle drives watch touches, locked-limit fills, stops and targets.
- Polling the same completed candle does not create duplicate direction/model changes.
- A live candle range observed before a watch or limit existed cannot retrospectively trigger that state.
- A fill candle cannot falsely apply price movement that occurred before the order existed.
- After TP1 moves the active stop to break-even, an earlier low/high from that same OHLC candle cannot falsely stop the runner.
- Same-candle price crossings that occur after monitoring/arming remain detectable through incremental observation snapshots.

## Chart and setup panel

- A touched watch line changes to `TOUCHED · CONFIRM LONG/SHORT`.
- The setup panel shows `Watch Touched · Awaiting Confirmation` and the confirmation deadline.
- Entry, stop, targets and risk boxes remain hidden until the plan is actually armed.
- Fib Pullback Continuation displays its 50% and 61.8% zone in clean mode without adding the full OTE label set.

## Validation

The local package passed:

- `123` pytest tests;
- Python compilation;
- JavaScript syntax validation for `app.js`, `trading_chart.js` and `boot.js`.

This validation did not include the user's live Databento entitlement, Railway environment, installed browser/PWA cache, broker routing or device-specific forward testing.
