# TradeIQ v2.7 — Deterministic Decision Brain

## Added

- Central read-only `DecisionBrainService` for entry-model selection.
- Twelve deterministic entry-model rankings:
  - Liquidity Sweep + Structure Shift
  - Supply/Demand Retest
  - OTE Retracement
  - Gamma Flip Reclaim
  - FVG Retest
  - Order Block Retest
  - EMA Pullback
  - VWAP Reclaim
  - Break & Retest
  - Trend Continuation
  - Inverse FVG
  - SMT Divergence
- Primary model, backup models, score, trigger and missing-confirmation metadata.
- Model switching while a setup remains in `WATCHING`.
- `GET /api/decision-brain` and `GET /api/entry-models`.

## Safety

Claude remains read-only. The Decision Brain cannot bypass session, history, risk/reward, confluence or lifecycle gates.

## Data limitation

SMT and Inverse FVG stay unqualified until the required deterministic data is present. They are not fabricated.
