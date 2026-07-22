# TradeIQ v3.1.0 — Adaptive Execution and Institutional Clusters

## Added

- Institutional Confluence Cluster that combines independent evidence categories without double-counting related labels.
- Single-model setups remain valid when their own model confidence is stronger than the composite cluster.
- Adaptive execution selector chooses `MARKET`, `LIMIT`, `STOP`, or `NONE` after deterministic confirmation.
- Execution freshness score and distance from ideal entry.
- Market entries fill immediately only when price remains close to the ideal entry, the structural stop is valid, and at least 2R remains.
- Resting orders automatically expire when TP1 is reached before fill or price departs beyond the freshness threshold.
- UI now identifies the selected execution type and composite cluster score.

## Safety

- No chasing after a missed move.
- Related concepts such as OTE/Fib and Supply/Order Block are grouped into evidence categories.
- Claude remains read-only.
- Market data health and session gates remain authoritative.
