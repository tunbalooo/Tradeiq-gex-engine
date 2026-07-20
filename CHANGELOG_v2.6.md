# TradeIQ v2.6 — Persistent Setup Memory

- Restores active WATCHING, WAITING_FOR_LIMIT, FILLED, and TP1_HIT setups after backend/Railway restart.
- Preserves setup ID, lifecycle timing, locked plan, transition reason, and last processed candle.
- Adds `GET /api/setups/{setup_id}/timeline`.
- Adds desktop/mobile Lifecycle Memory panels.
- Supplies recent timeline context to Claude without granting write authority.
- Adds the canonical `TRADEIQ_INSTITUTIONAL_ENTRY_ENGINE_SPEC.md` living specification.
- API version: `2.6.0-persistent-setup-memory`.
