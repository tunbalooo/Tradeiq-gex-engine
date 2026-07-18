"""Run this once before starting the full dashboard."""

import os
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("DATABENTO_API_KEY")
if not key or not key.startswith("db-"):
    raise SystemExit("DATABENTO_API_KEY is missing from .env")

import databento as db

records = 0


def on_record(record):
    global records
    if hasattr(record, "close"):
        records += 1
        close = getattr(record, "pretty_close", None)
        print(f"NQ record {records}: close={close} ts={getattr(record, 'pretty_ts_event', record.ts_event)}")


client = db.Live(key=key)
client.subscribe(
    dataset=os.getenv("DATABENTO_DATASET", "GLBX.MDP3"),
    schema="ohlcv-1s",
    stype_in="continuous",
    symbols=[os.getenv("DATABENTO_FUTURES_SYMBOL", "NQ.v.0")],
)
client.add_callback(on_record)
client.start()
client.block_for_close(timeout=15)

print(f"Connection test complete. Received {records} NQ OHLCV records.")
if records == 0:
    print("No records can be normal while the market is closed. Check the Databento portal and /api/health after startup.")
