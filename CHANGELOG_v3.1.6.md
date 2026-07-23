# Changelog v3.1.6

- Added location, confirmation, execution and final trade quality scores.
- Prevented non-executable locations from receiving a displayed trade grade.
- Persisted actual trigger model beneath composite cluster context.
- Added deterministic thesis fingerprinting.
- Added same-thesis terminal and post-stop re-entry locks.
- Restored thesis locks after server/Railway restart.
- Added `/api/scans/history`.
- Split published Trade Log from Scanner Log.
- Collapsed duplicate scanner rows by thesis fingerprint.
- Excluded scanner rows and unfilled orders from trade performance.
- Grouped analytics by actual trigger model.
- Added persistent `THESIS_LOCK_MAX_MINUTES` configuration.
- Updated frontend cache and API version to v3.1.6.
