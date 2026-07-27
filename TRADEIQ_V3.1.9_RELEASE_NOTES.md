# TradeIQ v3.1.9 — Trader Scalper Engine

## Why this release exists

The previous lifecycle could hold a high-quality location for too long while waiting for a perfect five-minute confirmation. A trader would either execute, invalidate, or move to the next idea. v3.1.9 changes the engine from a slow location monitor into an execution-first scalper while retaining GEX, OTE, supply/demand, VWAP, EMA, liquidity, and institutional market-map context.

## Core changes

- Scalper mode is enabled by default and can be disabled with `SCALPER_MODE_ENABLED=false`.
- Both LONG and SHORT are evaluated every cycle; the engine selects the side with the strongest execution-ready evidence instead of defaulting to one directional thesis.
- Model structure and confirmation use closed 1-minute candles. Five-minute structure remains higher-timeframe context.
- Monitoring expires after 8 minutes by default instead of 30 minutes.
- Confirmation uses 1-minute bars and normally has 2–5 minutes to complete depending on the model.
- Scalper mode does not extend an unsuccessful confirmation window.
- Direction/model replacement requires one new closed candle instead of two.
- Same-thesis terminal locks are reduced to 15 minutes unless a fresh structure event appears sooner.
- Scalp targets use a minimum 0.8R TP1 and 1.5R TP2 safety gate instead of forcing every opportunity to retain 2R.
- Continuation market-entry tolerance and nearby stop-entry tolerance are widened moderately for fast moves.
- Retracement limits remain restricted to fresh, nearby, structurally valid levels with room before opposing liquidity.
- The interface now displays `Scalp Readiness`, calculated from location, confirmation, and execution quality. A 97% location can no longer appear as 97% trade readiness when execution quality is zero.
- The setup panel displays the exact missing confirmation, freshness, target-room, or execution condition instead of the generic `WAITING FOR PRICE REACTION` message.
- All cluster and scan-state thresholds now use the active Scalper/Desk configuration consistently.
- `/api/settings` now reports the active execution mode, expiry, confirmation, entry-score and reward gates.
- Frontend assets are cache-busted to `v=319`, preventing desktop browsers from retaining the old slow lifecycle after deployment.

## Default scalp configuration

```env
SCALPER_MODE_ENABLED=true
SCALP_SETUP_EXPIRY_MINUTES=8
SCALP_WATCH_CONFIRMATION_MINUTES=2
SCALP_CONFIRMATION_BAR_MINUTES=1
SCALP_DIRECTION_SWITCH_CONFIRM_BARS=1
SCALP_THESIS_LOCK_MAX_MINUTES=15
SCALP_SETUP_CONFIDENCE_FLOOR=35
SCALP_SETUP_WATCH_MODEL_SCORE=50
SCALP_ENTRY_MODEL_ARM_SCORE=62
SCALP_MIN_TP1_R=0.8
SCALP_MIN_TP2_R=1.5
```

## Safety retained

- Closed-candle model confirmation
- Live-candle touch/fill/stop/target processing
- Structural stop validation
- No chasing after targets are reached
- No distant continuation limits
- Opposing-liquidity checks
- Same-thesis re-entry locks
- Claude remains read-only
- Market Radar remains informational until the active engine validates execution

## Verification

- 208 automated tests passed
- Python compilation passed
- Frontend JavaScript syntax checks passed
- Existing Claude and Market Radar resilience tests passed
- New scalper lifecycle, dual-direction, 1.5R execution, and readiness-display tests passed

## Limitations

This release changes deterministic execution behavior but does not prove profitability. The full production engine still needs a historical Databento replay with realistic fees, slippage, contract rollover, and out-of-sample validation before thresholds are treated as statistically proven.
