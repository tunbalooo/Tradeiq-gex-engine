# TradeIQ v3.0 Release Notes

## Release

`3.0.0-institutional-decision-platform`

## Main Upgrade

TradeIQ now operates as a persistent deterministic decision platform rather than a single confidence scanner. It ranks multiple execution models, records model switches, keeps GEX levels stable, manages TP1/runner logic and exposes read-only model analytics.

## New API Endpoints

- `GET /api/decision-brain`
- `GET /api/entry-models`
- `GET /api/analytics/summary`

## Configuration

Optional new variables:

```env
ENTRY_MODEL_MIN_SCORE=55
MOVE_STOP_TO_BREAKEVEN_AFTER_TP1=true
PARTIAL_EXIT_PERCENT=50
```

Defaults are already included; no new Railway variables are required unless different values are desired.

## Verification Performed

```text
104 passed
```

Also completed:

- Python compile validation
- Frontend `app.js`, `trading_chart.js` and `boot.js` syntax validation
- FastAPI endpoint smoke tests through `TestClient`

No Databento live-market session, Claude API call, broker connection or Railway deployment was executed in this environment.

## Install

Stop the local server, extract the v3.0 ZIP and copy its project contents over the existing TradeIQ folder. Preserve the existing `.env`.

Run:

```powershell
python -m pytest -q
```

Expected:

```text
104 passed
```

Then:

```powershell
git add .
git status
```

Confirm `.env` is not listed, then:

```powershell
git commit -m "Release TradeIQ v3.0 institutional decision platform"
git push origin main
```

After Railway deploys, refresh twice. The API version should show:

```text
3.0.0-institutional-decision-platform
```
