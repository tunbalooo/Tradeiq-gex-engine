# TradeIQ v3.0.9 — Chart Pipeline Integrity

## Purpose

This release corrects three data-pipeline behaviours that could make the chart misleading or unstable during long-running sessions.

## Changes

### Time-aware price-regime filtering

The frontend still rejects an abrupt price-regime change when adjacent bars are contiguous, preserving the existing protection against mixed contracts or corrupt data. It no longer treats a large price change across a real session gap as corruption.

Session gaps now exempted from truncation include:

- CME daily maintenance breaks
- Weekend reopen gaps
- Continuous-contract rollover gaps separated in time

### Honest simulated-feed health

The local generator now reports `SIMULATED` and `data_fresh: false`. It can no longer produce a green live-feed state that could be mistaken for Databento data.

### Bounded live overlay

The Databento reconnect overlay is capped at the service candle limit. This prevents one dictionary entry per minute from accumulating for the lifetime of a Railway process.

## Intentionally unchanged

Backend and frontend candle sanitation remain separate. The backend protects stored/aggregated data, while the frontend protects rendering and cached merges. Their thresholds were not changed in this release.
