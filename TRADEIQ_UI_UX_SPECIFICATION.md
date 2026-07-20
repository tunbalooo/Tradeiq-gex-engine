# TradeIQ UI/UX Specification

**Version:** 3.0.1

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

- Watch trigger: dashed amber line with `NO ORDER` language.
- Locked entry: fixed limit line.
- Initial stop: fixed red line and fixed risk box.
- Active stop after TP1: separate amber break-even line.
- Targets remain fixed.
- GEX levels remain stable until refresh.
- Automatic vertical scaling follows visible candle OHLC only; off-screen GEX/Fib/zone/target levels must not flatten candles.
- 1m/2m defaults show fewer bars so candle bodies remain readable.
- Symbol/timeframe viewports are remembered independently.
- Invalid, duplicated or out-of-order bars must never be rendered.

## Mobile

- Mobile is a purpose-built chart workspace, not a shrunken desktop.
- Maintain one-finger pan, pinch zoom, stable history, fullscreen and crosshair behavior.
- Setup, Claude, News and GEX use dedicated mobile panes.

## History and Analytics

Setup History includes model, grade, initial/active stop, management state and result. Model analytics are explicitly read-only.
