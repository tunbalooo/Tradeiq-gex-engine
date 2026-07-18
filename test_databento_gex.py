"""Fetch one native NQ GEX snapshot using the same service as the dashboard."""

import asyncio
from dotenv import load_dotenv

load_dotenv()

from backend.services.databento_gex import gex_service
from backend.services.market_data import market_data_service


async def main():
    await market_data_service.start()
    ok = await gex_service.refresh()
    print("Refresh:", ok)
    print("Health:", gex_service.health())
    summary = gex_service.get_summary(market_data_service.current_price)
    if summary:
        print(summary.model_dump(mode="json"))
    await market_data_service.stop()


if __name__ == "__main__":
    asyncio.run(main())
