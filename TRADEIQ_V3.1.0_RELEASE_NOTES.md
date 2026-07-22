# TradeIQ v3.1.0 Release Notes

TradeIQ can now execute a high-confidence single model or combine several independent institutional signals into a composite cluster. After confirmation, the deterministic engine selects the appropriate execution method: market, limit, stop, or no entry.

A setup is not forced into a limit order. Strong liquidity/MSS, VWAP reclaim, Gamma reclaim, trend continuation, SMT, or composite-cluster setups may use a market entry while fresh. Retracement models generally prefer limits. Break-and-retest models may use stop entries. If a target is reached before fill or price moves too far away, the setup is recorded as missed and the engine scans again.

Validation: 152 tests passed. Live Railway/Databento forward testing is still required.
