from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.models.db_models import TradeSetupRecord
from backend.services.dashboard_service import build_dashboard_meta
from backend.services.databento_gex import gex_service
from backend.services.market_data import market_data_service
from backend.services.setup_lifecycle import setup_lifecycle_service
from backend.services.setup_service import build_candidate_setup, build_current_setup, save_setup
from backend.services.timeframes import aggregate_candles

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    market = market_data_service.health()
    return {
        "status": "ok" if market.get("candle_count", 0) else "degraded",
        "mode": market["mode"],
        "data_source": market["data_source"],
        "market": market,
        "gex": gex_service.health(),
        "setup_lifecycle": setup_lifecycle_service.health(),
    }


@router.get("/market/snapshot")
def market_snapshot(
    timeframe: int = Query(default=1, ge=1, le=240),
    limit: int = Query(default=1000, ge=50, le=2400),
):
    base = market_data_service.snapshot(limit=limit)
    candles = aggregate_candles(base, timeframe)
    change, change_percent = market_data_service.price_change()
    return {
        "symbol": market_data_service.symbol,
        "price": market_data_service.current_price,
        "change": change,
        "change_percent": change_percent,
        "timeframe_minutes": timeframe,
        "data_source": market_data_service.data_source,
        "candles": candles,
    }


@router.get("/gex/summary")
def gex_summary():
    return build_candidate_setup().gex


@router.post("/gex/refresh")
async def refresh_gex():
    refreshed = await gex_service.refresh()
    return {"refreshed": refreshed, "gex": gex_service.health()}


@router.get("/setup/current")
def current_setup():
    return build_current_setup()


@router.get("/dashboard")
def dashboard_data():
    setup = build_current_setup()
    return {"setup": setup, "meta": build_dashboard_meta(setup)}


@router.post("/setup/recalculate")
def recalculate_setup(db: Session = Depends(get_db)):
    setup = build_current_setup()
    save_setup(db, setup)
    return setup


@router.post("/setup/reset")
def reset_setup():
    setup_lifecycle_service.reset()
    return {"reset": True, "setup_lifecycle": setup_lifecycle_service.health()}


@router.get("/setups/history")
def setup_history(limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(TradeSetupRecord).order_by(TradeSetupRecord.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))
