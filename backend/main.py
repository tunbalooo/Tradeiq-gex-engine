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
from backend.services.market_data import market_data_service
from backend.services.setup_service import build_current_setup


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(router)
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(Path("frontend/index.html"))


@app.websocket("/ws/market")
async def market_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            candle = market_data_service.next_candle()
            setup = build_current_setup()
            meta = build_dashboard_meta(setup)
            await websocket.send_json(
                {
                    "type": "market_update",
                    "candle": candle.model_dump(mode="json"),
                    "setup": setup.model_dump(mode="json"),
                    "meta": meta.model_dump(mode="json"),
                }
            )
            await asyncio.sleep(settings.update_interval_seconds)
    except WebSocketDisconnect:
        return
