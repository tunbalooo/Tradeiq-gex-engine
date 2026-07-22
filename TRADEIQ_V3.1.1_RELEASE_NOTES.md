# TradeIQ v3.1.1 Release Notes

## Flexible institutional clusters

TradeIQ no longer requires exactly three independent categories before recognizing a composite setup.

- **Exceptional 2-factor:** minimum 76 composite score, confirmation strength 2, 75% confidence and 70% execution freshness.
- **Standard 3-factor:** minimum 72 score, model-native confirmation, 60% confidence and 45% freshness.
- **High-priority 4+:** minimum 70 score, model-native confirmation and 30% freshness.

A stronger single model may still remain primary. If a preferred cluster fails its stricter quality gate but the single model remains executable, TradeIQ uses the single model instead of cancelling the opportunity.

## Safety retained

Every path still requires a valid entry, structural stop, clear target path, live-data health and at least 2R. Related evidence is grouped to prevent double-counting.

## Validation

`159 passed`
