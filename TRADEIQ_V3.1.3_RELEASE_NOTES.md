# TradeIQ v3.1.3 Release Notes

## Institutional Market Map

TradeIQ now converts raw market references into a compact ranked level ladder instead of treating every horizontal line as equally important.

The map combines nearby evidence from independent source groups:

- GEX walls, Gamma Flip, Maximum Pain and strong GEX nodes;
- 5-minute, 15-minute, 1-hour and 4-hour supply/demand zones;
- Fib 50%, 61.8%, 70.5% and 78.6% retracement levels;
- VWAP and one-standard-deviation value references;
- session highs/lows and previous buy-side/sell-side liquidity.

Related references are clustered by ATR/tick-aware proximity. Every cluster exposes its range, role, score, independent source count, contributors, freshness and live state:

- `APPROACHING`
- `TESTING`
- `REJECTING`
- `ACCEPTING`
- `DISTANT`

A cluster is location context only. It cannot create a trade by itself. The existing model-native confirmation, confidence, execution freshness, liquidity-room, stop and minimum-R gates remain mandatory.

## Cleaner chart

Clean mode now displays only:

- the current actionable institutional cluster;
- nearest opposing liquidity;
- or the nearest support and resistance when no cluster is actionable;
- locked entry, stop and targets after a plan is published.

The underlying raw GEX, Fib, zone and VWAP data remains available when Clean mode is disabled.

## Risk integration

Ranked opposing market-map clusters are added to the deterministic target candidate list. A nearby opposing cluster can block a poor entry or become TP1/TP2 when it offers valid reward. Accepted-through clusters are excluded from targets.

## API and Claude

New endpoint:

```text
GET /api/market-map
```

Claude receives the map as read-only context and is explicitly instructed not to treat a cluster touch as an entry.

## Verification

- 174 automated tests passed.
- Python compilation passed.
- Frontend JavaScript syntax checks passed.

The cluster weights and thresholds remain deterministic design choices, not proven profitability. Production-parity historical replay and live forward testing are still required.
