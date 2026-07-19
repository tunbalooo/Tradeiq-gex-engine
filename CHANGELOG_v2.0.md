# TradeIQ v2.0 — Locked Trade Plans

## Trading behavior

- Entry, stop, TP1, TP2 and the risk/reward box are hidden while TradeIQ is only scanning or showing a preview candidate.
- The chart reveals the complete trade plan only after the deterministic engine arms a setup in `WAITING_FOR_LIMIT`.
- Once armed, the original entry, stop and targets are frozen. Live recalculation may update confidence, confluence, GEX, zones and commentary, but it cannot move the active trade levels.
- The locked levels remain visible while the setup is `WAITING_FOR_LIMIT`, `FILLED` or `TP1_HIT`.
- The trade overlay is removed after `TP2_HIT`, `STOPPED`, `EXPIRED` or `INVALIDATED`.
- Preview trade levels no longer affect chart autoscaling.

## Interface

- Setup cards show dashes for entry, stop and targets until an actual setup is armed.
- Preview messaging now says `SCANNING — NO ACTIVE SETUP`.
- FastAPI and the installed web-app cache now report v2.0.

## Unchanged safeguards

- Session status still does not modify confidence.
- Claude remains read-only.
- GEX and market context overlays can continue updating independently.
