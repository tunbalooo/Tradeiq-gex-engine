# TradeIQ v1.2 — Multi-Market Futures

## Added

- Global active-market selector for NQ, MNQ, ES, MES, GC, and MGC.
- Instrument registry containing continuous Databento symbols, tick sizes, price precision, session hours, simulation profiles, news terms, and GEX-parent mappings.
- `GET /api/instruments` and `POST /api/market/symbol`.
- Dynamic chart labels, prices, precision, news heading, setup symbol, and page titles.
- Market-aware Finnhub ranking.
- Market-aware Claude snapshot cache invalidation.
- Parent-market GEX labels for MNQ, MES, and MGC.
- Market-aware RTH/session handling, including the equity-index 16:15–16:30 ET halt only for NQ/MNQ/ES/MES.

## GEX parents

- NQ / MNQ → NQ options (`NQ.OPT`)
- ES / MES → ES options (`ES.OPT`)
- GC / MGC → standard Gold options (`OG.OPT`)

## Preserved

- Classic dashboard and chart workstation.
- Confidence-score independence from session status.
- Session gate limited to actionable state and order arming.
- Claude read-only restrictions.
- Finnhub news has no scoring effect.

## Development-stage limitation

The selected market is global to the running service. This is appropriate for the current single-user deployment. Per-user market state requires authentication/session storage later.
