# TradeIQ v3.1.2 — Silent Monitoring & Real Entry Routing

## Added

- Silent pre-entry monitoring on desktop, mobile and Market Radar.
- Real retracement-limit qualification using model family, distance, freshness, resting-side validity and liquidity room.
- Fast continuation execution that permits MARKET only while the live price remains close and at least 2R remains from the live price.
- Nearby STOP execution for break-and-retest proof triggers.
- Composite clusters inherit the execution family of the strongest underlying single model.
- Automatic Claude lifecycle commentary begins only after an executable plan has been published; manual Analyze remains available.

## Changed

- Watch triggers and structural invalidations are no longer rendered as entry lines.
- Developing model rankings, direction, confidence and candidate prices remain private until a real execution plan is locked.
- Continuation models no longer fall back to distant limit orders after the move has left.
- A retracement limit must be within the real-limit distance envelope and have adequate room before TP1/opposing liquidity.
- Chart autoscaling ignores internal watch prices.

## Safety

- No broker routing was added.
- The deterministic engine remains the sole decision authority.
- Claude remains read-only.
- Market, limit and stop plans still require confirmation, target-not-blocked, minimum 2R and live-data safety.
