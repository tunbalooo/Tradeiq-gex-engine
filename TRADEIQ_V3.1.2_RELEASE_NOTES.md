# TradeIQ v3.1.2 Release Notes

TradeIQ now monitors developing opportunities internally and publishes a price only when the deterministic engine has a real executable plan.

## What the trader sees

Before execution qualifies, the Trade Desk shows `SCANNING QUIETLY` and no entry, stop, target, model ranking, direction or watch line. When a plan qualifies, TradeIQ publishes the exact execution type and locked levels:

- `MARKET ENTRY` for a fresh confirmed continuation or a retracement that confirms at the intended price;
- `LIMIT ENTRY` for a nearby, fresh, model-qualified retracement on the correct side of market;
- `STOP ENTRY` for a nearby breakout trigger that must prove continuation;
- no entry when the move has left, liquidity is too close, freshness is inadequate or 2R no longer remains.

## Real retracement limits

A resting limit is not published merely because a model has a theoretical trigger. It must:

1. belong to a retracement model such as OTE, supply/demand, FVG, order block, EMA pullback or Fib continuation;
2. be confirmed by the model-native contract;
3. sit on the correct resting side of the current market;
4. remain within the distance/freshness envelope;
5. retain adequate room before TP1 or opposing liquidity;
6. preserve the structural stop and at least 2R.

## Fast continuation

Liquidity sweep/MSS, Gamma Flip reclaim, VWAP reclaim, trend continuation and SMT-style continuation can enter at market only while the live price is still near the intended entry and at least 2R remains from the current price. Once the move leaves, TradeIQ records no execution and does not manufacture a distant pullback limit.

## Composite clusters

An Institutional Confluence Cluster uses the execution family of its strongest underlying valid model. A cluster led by OTE or supply/demand can use a qualified limit; a cluster led by liquidity sweep or trend continuation can use fast market execution.

## Claude

Automatic Claude commentary remains silent during internal monitoring. It starts after a real plan is armed/filled or when explaining a later lifecycle event. Manual Analyze remains available as a read-only diagnostic.

## Validation

- 169 automated tests pass.
- Python compilation passes.
- Frontend JavaScript syntax checks pass.
- No broker execution or profitability claim is included.
