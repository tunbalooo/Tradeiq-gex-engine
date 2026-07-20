# TradeIQ v2.9 — Professional Trade Management

## Added

- Immutable initial stop plus separate active stop.
- Configurable partial exit at TP1 (default 50%).
- Automatic runner stop to break-even after TP1.
- Runner state and management-action history.
- Maximum favorable and adverse excursion tracking.
- Break-even-after-TP1 outcome handling and R calculation.
- Initial and active stop lines are distinguished on the chart.

## Safety

TradeIQ still does not connect to a broker or submit real orders. All lifecycle fills and management actions are deterministic simulations from candle data.
