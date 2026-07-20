# TradeIQ v3.0 — Institutional Decision Platform

## Added

- Seven-category institutional confidence score:
  - Trend 20
  - Structure 20
  - GEX 20
  - Liquidity 15
  - Momentum 10
  - Volume 10
  - Session 5
- Grades: A+, A, B+, B, C and AVOID.
- Setup panel displays the primary entry model, backups, grade, initial stop, active stop and management state.
- Ranked model list on desktop and chart-side setup panels.
- Read-only model analytics and setup-history enhancements.
- `GET /api/analytics/summary`.
- Claude lifecycle payload now includes model selection and trade-management state.
- PWA asset cache upgraded to `tradeiq-v3.0-shell`.

## Version

`3.0.0-institutional-decision-platform`

## Verification

- Python test suite: 104 passed.
- Python compilation: passed.
- Frontend JavaScript syntax validation: passed.
