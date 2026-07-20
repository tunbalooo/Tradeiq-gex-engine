# TradeIQ Master Specification

**Product version:** 3.0.0-institutional-decision-platform  
**Document version:** 3.0  
**Status:** Living source of truth

## 1. Product Purpose

TradeIQ is an institutional-style futures decision-support platform for NQ/MNQ, ES/MES, GC/MGC and later CL, Forex and Crypto. It combines deterministic market structure, GEX, liquidity, supply/demand, OTE, VWAP, EMA alignment and risk logic.

TradeIQ answers:

> Where is institutional participation likely, what is the engine waiting for, and what invalidates the plan?

It is not a broker, profit guarantee or autonomous AI trader.

## 2. Authority Boundaries

- **TradeIQ deterministic engine:** owns setup creation, scoring, state changes, entries, stops, targets and management rules.
- **Decision Brain:** ranks eligible entry models and selects the primary/backup path.
- **Claude:** reads recorded engine state and explains it. Claude cannot modify any trading field.
- **UI:** displays engine state and never creates its own setup logic.

## 3. Lifecycle

`PREVIEW_ONLY → WATCHING → WAITING_FOR_LIMIT → FILLED → TP1_HIT → TP2_HIT/STOPPED`

Terminal alternatives:

- `EXPIRED`
- `INVALIDATED`
- `UNCONFIRMED_TOUCH`

A `WATCHING → WATCHING` event records a deterministic switch to a stronger secondary entry model.

## 4. Implemented v3.0 Modules

- Live/historical market data service.
- GEX service with snapshot-stable dealer levels.
- Supply/demand and market-structure engines.
- OTE and risk engines.
- Persistent setup memory and lifecycle timeline.
- Claude lifecycle explanation queue.
- Decision Brain and 12-model ranking.
- Institutional confidence categories.
- TP1 partial, break-even runner and excursion tracking.
- Read-only model analytics.
- Responsive desktop/mobile web UI.

## 5. Entry Models

1. Liquidity Sweep + Structure Shift
2. Supply/Demand Retest
3. OTE Retracement
4. Gamma Flip Reclaim
5. Fair Value Gap Retest
6. Order Block Retest
7. EMA Pullback
8. VWAP Reclaim
9. Break & Retest
10. Trend Continuation
11. Inverse FVG
12. SMT Divergence

Each model returns a transparent score, eligibility, trigger, invalidation, evidence and missing data. Unsupported evidence remains missing rather than simulated.

## 6. Confidence

Confidence is deterministic and totals 100 points:

| Category | Maximum |
|---|---:|
| Trend | 20 |
| Structure | 20 |
| GEX | 20 |
| Liquidity | 15 |
| Momentum | 10 |
| Volume | 10 |
| Session | 5 |

The entry model has a separate model score. Both the setup score and mandatory safety gates must qualify before a limit plan is armed.

## 7. GEX Policy

Gamma Flip, Call Wall, Put Wall and major nodes remain fixed until the option-position snapshot is refreshed. Fallback GEX remains fixed for the configured refresh window. GEX is contextual and cannot create a trade alone.

## 8. Trade Management

After a locked limit fills:

- Initial stop remains recorded and immutable.
- Active stop begins at the initial stop.
- TP1 secures the configured partial percentage (default 50%).
- The runner stop moves to break-even when enabled.
- TP2 completes the runner.
- MFE and MAE are recorded in points.

## 9. Persistence and Replay

The active lifecycle object survives backend restarts. Every transition is stored with its candle time, price and exact reason. Timeline data supports Claude explanations and setup replay.

## 10. Current Limitations

- No broker order routing.
- Candle-based fill simulation cannot determine intrabar ordering; ambiguous candles are treated conservatively.
- SMT requires synchronized comparison-market data and therefore remains unavailable when that feed is absent.
- Order Block and FVG models use deterministic data already derived by the current structure/zone engine; they are not full depth-of-market models.
- Analytics are descriptive and do not adapt live model weights.
- Multi-symbol selection exists, but simultaneous portfolio monitoring is not yet implemented.
