# TradeIQ v3.1.4 Release Notes

## Executable Bracket Plans

TradeIQ now presents every published executable setup as a professional chart bracket rather than a collection of unrelated horizontal lines.

### Chart contract

When the deterministic engine publishes a locked plan, the chart shows:

- exact `BUY MARKET`, `SELL MARKET`, `BUY LIMIT`, `SELL LIMIT`, `BUY STOP`, or `SELL STOP` wording;
- the exact entry price on the right price scale;
- a translucent green reward area from entry to TP2;
- a translucent red risk area from entry to the structural stop;
- TP1 as an internal dashed guide;
- TP2 and SL labels inside the bracket when space permits;
- lifecycle wording for `ARMED`, `FILLED`, and `TP1 HIT`;
- the plan's risk/reward ratio in the entry badge when available.

### Silent monitoring remains enforced

The bracket is drawn only when `hasLockedTradePlan(setup)` is true. Preview, watching, theoretical, and silently monitored levels do not receive an entry box. The release does not convert a watch level into an order.

### Execution logic is unchanged

v3.1.4 changes presentation, not signal generation. The following existing gates still decide whether a plan may be published:

- model-native confirmation;
- single-model or institutional-cluster eligibility;
- execution freshness;
- nearby-real-limit requirements;
- opposing-liquidity room;
- structural stop validity;
- minimum reward-to-risk;
- market-data health;
- no-chase and target-reached-before-fill protection.

### Cache refresh

The application shell version is now `tradeiq-v3.1.4-executable-bracket-plans-shell`, and all main frontend assets use `?v=314` to prevent desktop browsers or installed mobile apps from retaining the previous chart renderer.

### Verification

- `179 passed`
- Python compilation passed
- Frontend JavaScript syntax checks passed
- ZIP integrity and SHA-256 verification passed

The release has not been deployed to Railway and has not been forward-tested against the production Databento stream.
