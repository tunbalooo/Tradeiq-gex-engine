# TradeIQ Development Roadmap

**Current release:** 3.0.2-entry-chart-stability

## Completed

- [x] v2.5 Claude lifecycle explanations
- [x] v2.6 Persistent setup memory and timeline
- [x] v2.7 Decision Brain and deterministic model ranking
- [x] v2.8 Stable GEX snapshot and dealer interpretation
- [x] v2.9 Partial/runner management and break-even stop
- [x] v3.0 Institutional confidence, analytics and integrated UI
- [x] v3.0.1 Small-timeframe candle integrity, price-first autoscale and viewport persistence
- [x] v3.0.2 Model-specific entry gates, closed-candle lifecycle stability, clean chart mode and filtered setup history

## Next — v3.0.3 Live Forward-Test Corrections

- [ ] Validate watch and arm thresholds on live NQ/MNQ 1m, 2m and 5m data
- [ ] Review cancellation and unconfirmed-touch rates by session
- [ ] Tune label priority from real device screenshots
- [ ] Confirm installed PWA cache replacement on iPhone/iPad and Windows
- [ ] Add an optional diagnostics panel showing the exact missing confirmation groups

## v3.1 Quality and Data Depth

- [ ] Native synchronized SMT feed for NQ/ES and related pairs
- [ ] Explicit FVG and inverse-FVG lifecycle objects
- [ ] Dedicated order-block/breaker/rejection-block detector
- [ ] Historical model-by-model backtest using archived GEX snapshots
- [ ] More robust session/news risk gates

## v3.2 Execution and Portfolio Workspace

- [ ] Simultaneous multi-symbol monitoring
- [ ] Portfolio heat map
- [ ] Cross-market correlation dashboard
- [ ] Alert/webhook adapter with explicit user-controlled execution
- [ ] Advanced trailing policies

## v3.5 Data and Replay

- [ ] Full setup replay on historical candles
- [ ] Dealer-position history
- [ ] Model calibration by symbol/session/regime
- [ ] Downloadable journal and audit report

## v4.0 Research Goal

- [ ] Offline adaptive model weighting trained only on audited historical results
- [ ] Strict separation between research weights and live deterministic policy
- [ ] Walk-forward validation and drift monitoring
