# TradeIQ v1.4 — Fast Switch + Preview Clarity

## Performance

- Includes the v1.3 non-blocking Databento instrument switch.
- Previously loaded markets remain cached for fast return switching.
- First-time market history backfills in the background while the interface remains responsive.
- Finnhub general news is shared and filtered locally.
- Parent-market GEX refresh remains asynchronous.

## Preview clarity

- Chart setup panel now explains exactly why a plan is watch-only.
- Market-closed previews state that they use the latest closed data and may change at reopening.
- Databento-sync previews are explicitly marked temporary and not tradable.
- Preview chart price line is labelled `WATCH` instead of implying an order is active.

## Claude

- Compact analysis capped at 130 words.
- Avoids repeating entry, stop, and targets already shown in the setup panel.
- Clearly states that a preview is not a forecast, scheduled trade, or guarantee.
- Keeps confidence and execution permissions entirely under the deterministic TradeIQ engine.
