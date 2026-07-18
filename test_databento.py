"""
Databento connection test — run this FIRST, before we wire Databento into
TradeIQ. It streams a few seconds of live CME data for NQ futures.

Setup:
  1. Put your key in .env (never in code, never in chat):
       DATABENTO_API_KEY=db-your-key
  2. python -m pip install -U databento python-dotenv
  3. python test_databento.py

Expected: NQ market records printing. If the market is closed (weekend /
17:00-18:00 ET halt) you may see nothing — that is NOT a failed connection;
an auth error would raise immediately instead.
"""
from dotenv import load_dotenv
load_dotenv()

import databento as db

client = db.Live()  # reads DATABENTO_API_KEY from the environment

client.subscribe(
    dataset="GLBX.MDP3",
    schema="ohlcv-1s",
    stype_in="parent",
    symbols=["NQ.FUT"],
)
client.add_callback(print)
client.start()
client.block_for_close(timeout=10)
print("Done. If you saw records above, the connection works.")
