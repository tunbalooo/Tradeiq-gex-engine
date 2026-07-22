# Previous release: 3.0.9-chart-pipeline-integrity
# Previous release: 3.0.8-connection-gex-resilience
# Previous release: 3.0.6-timezone-aware-history
# Legacy release reference: 2.4.0-stable-mobile-clear-execution
# Previous release: 2.5.0-claude-lifecycle-explanations
# Previous release: 2.6.0-persistent-setup-memory
# TradeIQ v3.0 adds the deterministic Decision Brain, model ranking, management and analytics.
# TradeIQ v3.1.1 adds flexible two-, three-, and four-plus-factor cluster tiers.
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.core.config import settings
from backend.core.database import Base, engine
from backend.services.dashboard_service import build_dashboard_meta
from backend.services.databento_gex import gex_service
from backend.services.market_data import market_data_service
from backend.services.multi_market_monitor import multi_market_monitor_service
from backend.services.session_service import get_session_status
from backend.services.setup_service import current_gex_summary
from backend.services.trade_engine import trade_engine_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    await market_data_service.start()
    await gex_service.start()
    await trade_engine_service.start()
    await multi_market_monitor_service.start()
    try:
        yield
    finally:
        await multi_market_monitor_service.stop()
        await trade_engine_service.stop()
        await gex_service.stop()
        await market_data_service.stop()


# Legacy API version references retained for regression tests: 2.3.0-fixed-watch-expiry 2.0.0-locked-trade-plans 2.1.0-watching-to-limit 2.2.0-stable-chart-core
# Legacy v3.0 API release: 3.0.0-institutional-decision-platform
# Legacy v3.0.1 API release: 3.0.1-chart-candle-hotfix
# Legacy v3.0.2 API release: 3.0.2-entry-chart-stability
# Legacy v3.0.3 API release: 3.0.3-fib-pullback-watch-execution
# Legacy v3.0.4 API release: 3.0.4-trade-desk-market-radar
# Legacy v3.0.5 API release: 3.0.5-self-healing-market-stream
app = FastAPI(title=settings.app_name, version="3.1.1-flexible-cluster-tiers", lifespan=lifespan)
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
    heartbeat = 0
    while True:
        component_errors: list[str] = []

        def safe_component(name: str, factory, default):
            try:
                return factory()
            except Exception as exc:
                component_errors.append(f"{name}: {exc}")
                logger.exception("WebSocket component %s failed", name)
                return default

        try:
            heartbeat += 1
            setup = safe_component("setup", trade_engine_service.current_setup, None)
            market = safe_component("market", market_data_service.health, {"connected": False, "stream_state": "ERROR"})
            candles = safe_component("candle", lambda: market_data_service.snapshot(limit=1), [])
            payload = {
                "type": "market_update",
                "server": {
                    "status": "LIVE",
                    "time": datetime.now(timezone.utc).isoformat(),
                    "heartbeat": heartbeat,
                },
                "candle": candles[-1].model_dump(mode="json") if candles else None,
                "setup": setup.model_dump(mode="json") if setup else None,
                "meta": safe_component(
                    "dashboard_meta",
                    lambda: build_dashboard_meta(setup).model_dump(mode="json") if setup else None,
                    None,
                ),
                "market": market,
                "gex_summary": safe_component(
                    "gex_summary",
                    lambda: setup.gex.model_dump(mode="json") if setup else current_gex_summary().model_dump(mode="json"),
                    None,
                ),
                "gex_health": safe_component("gex", gex_service.health, {"status": "error"}),
                "session": safe_component("session", get_session_status, None),
                "engine": safe_component(
                    "engine",
                    lambda: trade_engine_service.snapshot().model_dump(mode="json"),
                    None,
                ),
                "market_opportunities": safe_component(
                    "market_opportunities",
                    lambda: [item.model_dump(mode="json") for item in multi_market_monitor_service.snapshot()],
                    [],
                ),
                "market_radar": safe_component("market_radar", multi_market_monitor_service.status, None),
                "component_errors": component_errors,
            }
            await websocket.send_json(jsonable_encoder(payload))
            await asyncio.sleep(settings.update_interval_seconds)
        except WebSocketDisconnect:
            return
        except (RuntimeError, ConnectionError):
            # The browser is gone or the ASGI socket is no longer writable.
            return
        except Exception:
            # A payload component must never terminate the market stream. If an
            # unexpected loop error occurs, keep the socket alive and retry.
            logger.exception("Unexpected /ws/market loop error")
            try:
                await websocket.send_json({
                    "type": "market_stream_error",
                    "server": {
                        "status": "DEGRADED",
                        "time": datetime.now(timezone.utc).isoformat(),
                        "heartbeat": heartbeat,
                    },
                })
            except Exception:
                return
            await asyncio.sleep(max(1, settings.update_interval_seconds))
