# TradeIQ v3.1.6 — Audit Quality & Lifecycle Integrity

API version: `3.1.6-audit-quality-lifecycle`.

## Why this release exists

A live audit showed many scanner rows, very few published entries, repeated rediscovery of the same thesis, and high grades attached to locations that never became executable. v3.1.6 corrects the lifecycle and reporting layer before any attempt is made to loosen thresholds.

## Quality separation

TradeIQ now reports four distinct scores:

- **Location Quality** — quality of the institutional level/cluster.
- **Confirmation Quality** — completion of the selected model's native trigger.
- **Execution Quality** — freshness, remaining reward and executable order route.
- **Trade Quality** — final weighted score, calculated only when an executable plan exists.

A scanner may show an `A` **Location Grade**, but `Trade Grade` remains `—` until a market, limit or stop plan passes every gate.

## Actual trigger model

When the primary context is `Institutional Confluence Cluster`, TradeIQ also persists and displays the actual trigger model used for execution, such as:

- Liquidity Sweep + Structure Shift
- OTE Retracement
- Order Block Retest
- FVG Retest

Performance analytics group results by this trigger model rather than by the generic cluster label.

## Separate logs

- **Trade Log · Published Entries** contains only plans that published a market, limit or stop order.
- **Scanner Log · Unique Theses** contains watches, confirmations, invalidations and expiries.
- Scanner rows never count as trades, wins, losses, average R or profit factor.
- Only filled trades count in performance analytics.

## Thesis fingerprint and re-entry lock

Every candidate receives a deterministic fingerprint from:

- symbol and direction;
- actual trigger model;
- institutional location bucket;
- latest direction-specific sweep/displacement/sequence event.

After `STOPPED`, `EXPIRED`, `INVALIDATED`, `UNCONFIRMED_TOUCH` or `TP2_HIT`, the same fingerprint is locked. A new setup is allowed only when price produces a genuinely new structural event or a materially different cluster/location.

Locks are persisted and restored after a Railway/server restart. The safety fallback is configurable with:

```env
THESIS_LOCK_MAX_MINUTES=240
```

## Historical duplicate collapse

The Scanner Log collapses repeated legacy rows with the same thesis fingerprint. Older rows without a fingerprint use a model/location/structure signature.

## UI changes

- The live gauge shows Location Quality while scanning and Trade Quality after a plan is locked.
- `Location Grade` changes to `Trade Grade` only after execution becomes valid.
- Composite context and actual trigger model are shown separately.
- The Setups page now contains distinct Trade Log, Scanner Log and Trigger Performance sections.

## Safety boundary

This release improves auditability and prevents repeated same-thesis losses. It does not prove profitability and does not loosen entry thresholds. Production-parity historical backtesting remains required before score weights are treated as validated.
