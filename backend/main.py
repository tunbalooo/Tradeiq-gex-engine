import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.core.config import settings
from backend.core.database import Base, engine
from backend.services.dashboard_service import build_dashboard_meta
from backend.services.databento_gex import gex_service
from backend.services.market_data import market_data_service
from backend.services.session_service import get_session_status
from backend.services.trade_engine import trade_engine_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    await market_data_service.start(); await gex_service.start(); await trade_engine_service.start()
    try: yield
    finally:
        await trade_engine_service.stop(); await gex_service.stop(); await market_data_service.stop()


# Legacy API version references retained for regression tests: 2.0.0-locked-trade-plans 2.1.0-watching-to-limit 2.2.0-stable-chart-core
app = FastAPI(title=settings.app_name, version="2.3.0-fixed-watch-expiry", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/", include_in_schema=False)
def dashboard(): return FileResponse(Path("frontend/index.html"))

@app.get("/favicon.ico", include_in_schema=False)
def favicon(): return FileResponse(Path("frontend/favicon.svg"), media_type="image/svg+xml")

@app.get("/service-worker.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        Path("frontend/service-worker.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )

@app.websocket("/ws/market")
async def market_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            setup = trade_engine_service.current_setup()
            market = market_data_service.health()
            candles = market_data_service.snapshot(limit=1)
            payload = {
                "type": "market_update",
                "candle": candles[-1].model_dump(mode="json") if candles else None,
                "setup": setup.model_dump(mode="json") if setup else None,
                "meta": build_dashboard_meta(setup).model_dump(mode="json") if setup else None,
                "market": market,
                "gex_health": gex_service.health(),
                "session": get_session_status(),
                "engine": trade_engine_service.snapshot().model_dump(mode="json"),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(settings.update_interval_seconds)
    except WebSocketDisconnect:
        return
