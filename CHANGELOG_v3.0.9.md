# v3.0.9

- Made frontend price-regime detection aware of genuine time gaps.
- Preserved the 8% contiguous-regime mismatch safeguard.
- Corrected simulated feed health to report `SIMULATED`, not `LIVE`.
- Bounded the Databento live reconnect overlay to `max_candles`.
- Added regression tests for all three changes.
