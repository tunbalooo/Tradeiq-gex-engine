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
from backend.services.trade_engine import trade_engine_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    await market_data_service.start(); await gex_service.start(); await trade_engine_service.start()
    try: yield
    finally:
        await trade_engine_service.stop(); await gex_service.stop(); await market_data_service.stop()


app = FastAPI(title=settings.app_name, version="0.5.0-pages-safe-engine", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/", include_in_schema=False)
def dashboard(): return FileResponse(Path("frontend/index.html"))

@app.get("/favicon.ico", include_in_schema=False)
def favicon(): return FileResponse(Path("frontend/favicon.svg"), media_type="image/svg+xml")

@app.websocket("/ws/market")
async def market_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            setup = trade_engine_service.current_setup()
            if setup:
                await websocket.send_json({"type":"market_update", "candle":market_data_service.latest_candle().model_dump(mode="json"), "setup":setup.model_dump(mode="json"), "meta":build_dashboard_meta(setup).model_dump(mode="json"), "market":market_data_service.health(), "gex_health":gex_service.health(), "engine":trade_engine_service.snapshot().model_dump(mode="json")})
            await asyncio.sleep(settings.update_interval_seconds)
    except WebSocketDisconnect:
        return
