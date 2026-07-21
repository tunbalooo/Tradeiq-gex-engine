# TradeIQ UI/UX Specification

**Version:** 3.0.3

## Design Language

- Dark institutional interface.
- Information-dense desktop layout.
- Touch-first mobile chart workspace.
- Minimal animation and no decorative AI widgets.
- Color is reserved for state, risk and direction.

## Setup Panel

Always show:

- Lifecycle status
- Direction
- Primary model and score
- Up to three backup models
- Confidence and grade
- Reason/missing confirmations through Claude
- Watch phase and exact next required event

Show only after `WAITING_FOR_LIMIT`:

- Locked entry
- Initial stop
- Active stop
- TP1 and source
- TP2 and source
- Risk/reward
- Risk/reward boxes

## Model Ranking

Display the five highest models. Clearly distinguish:

- Primary qualified model
- Qualified backups
- Developing/ineligible models and missing evidence

## Chart

### Default Clean Mode

Clean mode is enabled on first load. It keeps the core candle/EMA/trade view and only the nearest or selected institutional context. The user can turn Clean off to reveal the complete analytical map. Clean mode changes presentation only; it never changes scoring or trade state.


- Watch trigger: dashed amber line with `NO ORDER` language.
- After price touches the watch line, change its label to `TOUCHED · CONFIRM LONG/SHORT` without drawing a fill or risk plan.
- The setup panel must show `Watch Touched · Awaiting Confirmation`, the deadline and the structural invalidation.
- Locked entry: fixed limit line.
- Initial stop: fixed red line and fixed risk box.
- Active stop after TP1: separate amber break-even line.
- Targets remain fixed.
- GEX levels remain stable until refresh.
- Automatic vertical scaling follows visible candle OHLC only; off-screen GEX/Fib/zone/target levels must not flatten candles.
- 1m/2m defaults show fewer bars so candle bodies remain readable.
- Symbol/timeframe viewports are remembered independently.
- Invalid, duplicated or out-of-order bars must never be rendered.
- The latest live bar must pass the same malformed-wick test as historical bars.
- Duplicate right-axis tags are suppressed while their underlying lines remain visible.
- Default 1m/2m/5m visible ranges must preserve readable candle bodies.
- Fib Pullback Continuation clean mode shows only its 50%, 61.8% and shaded continuation band; it must not add duplicate OTE labels.


## Watch-State Language

The UI must distinguish location, confirmation and execution:

- `MONITORING LONG/SHORT`: price has not reached the watch trigger.
- `CONFIRMING LONG/SHORT`: price reached the trigger; no order is active.
- `WAITING_FOR_LIMIT`: the deterministic plan is armed and all levels are locked.
- `FILLED` / `TP1_HIT`: an actual managed position exists.
- `UNCONFIRMED_TOUCH`: the trigger was reached but confirmation expired; no order existed.

The UI must never use words such as “filled,” “active trade” or “risk remaining” during `WATCHING`.

## Mobile

- Mobile is a purpose-built chart workspace, not a shrunken desktop.
- Maintain one-finger pan, pinch zoom, stable history, fullscreen and crosshair behavior.
- Setup, Claude, News and GEX use dedicated mobile panes.

## History and Analytics

Setup History includes model, grade, initial/active stop, management state and result. Transient preview/scanning rows are hidden, and repeated rows from the same closed candle are suppressed. Model analytics are explicitly read-only.
