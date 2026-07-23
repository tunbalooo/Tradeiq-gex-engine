# TradeIQ v3.1.5 — Visible Scanning & Level Controls

## What changed

TradeIQ no longer looks empty while it is evaluating a setup. The Trade Desk now publishes the developing candidate direction, leading model, backup models, confidence grade, cluster and ranking. This information is explicitly marked as a live scan and not an order.

The chart has independent controls for Scan, Map, EMAs, GEX, Fib/OTE, S&D, Entry/SL/TP and VWAP/σ. Clean mode is optional and off by default. With Clean off, every available level in an enabled family is rendered. Preferences persist per browser.

## Execution safety

A scan line is never an entry. Entry, structural stop, TP1, TP2 and the risk/reward bracket still appear only after the deterministic engine selects an executable market, limit or stop plan.

## Deployment

API version: `3.1.5-visible-scanning-level-controls`.
