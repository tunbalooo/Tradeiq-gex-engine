# TradeIQ v3.1.8 — Claude & Radar Resilience

## Purpose

This release fixes two visible UI failures without changing TradeIQ's deterministic trade-entry, stop, target, confidence, or lifecycle rules.

## Claude desktop repair

The desktop panel previously depended on a single EventSource connection. A buffered or blocked SSE connection could leave the panel blank, and the status probe ran late enough in startup that another frontend failure could leave the badge at `CHECKING`.

v3.1.8 adds:

- an independent, early Claude status probe;
- an 8-second status timeout with two bounded retries;
- a 2 KB SSE flush prelude and immediate heartbeat event;
- a 9-second first-event watchdog and 75-second overall watchdog;
- automatic JSON fallback through `POST /api/ai/analysis` when SSE is blocked, buffered, disconnected, or times out;
- one shared backend lock and fingerprint cache for SSE and JSON, preventing duplicate Anthropic calls;
- clearer safe errors for disabled configuration, missing key/package, authentication, access, rate limit, timeout, and network failures;
- expanded `/api/ai/status` diagnostics: operational state, model used, last request, cache, and last error.

Claude remains read-only. It cannot change the engine's direction, score, entry, stop, targets, order state, or execution.

## Cross-Market Radar repair

The radar was scanning, but the frontend only showed model details when `alertable=true`. The active chart is intentionally never a background alert, so an A-grade active-market candidate could be displayed as only `Scanning internally`.

v3.1.8 now:

- separates `qualified` from `alertable`;
- keeps qualified active-market setups visible as `ACTIVE ENGINE`;
- displays developing direction, model, score, confidence, grade, and deterministic reason even before alert qualification;
- reports the exact missing gates, such as entry confirmation, minimum score, confidence, fresh data, direction, or model;
- distinguishes `SCANNING`, `DEVELOPING`, `STALE DATA`, `SETUP FORMING`, and `ACTIVE ENGINE`;
- counts qualified, developing, and alertable opportunities separately;
- preserves background notifications only for qualified inactive markets;
- surfaces scanner errors in the radar header instead of silently showing a generic card.

The radar remains informational. Opening a market is still required before the active engine can validate live GEX, risk, confirmation, and execution.

## Compatibility

No Railway variable names changed. Claude still requires:

```env
CLAUDE_ANALYSIS_ENABLED=true
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=...
```

## Verification

- 199 automated tests passed
- Python compilation passed
- All frontend JavaScript syntax checks passed
- Claude JSON fallback cache/deduplication test passed
- Claude SSE flush/heartbeat test passed
- Active-market radar visibility test passed
- Radar missing-gate diagnostics test passed
- API smoke checks passed

Live Anthropic billing/model access and production Databento behavior were not tested because production credentials are not present in the build environment.
