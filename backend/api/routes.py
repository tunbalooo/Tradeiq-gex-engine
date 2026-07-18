from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.core.config import settings
from backend.models.schemas import BacktestRequest, MarketSymbolRequest
from backend.services.backtest_service import run_backtest
from backend.services.claude_analysis import claude_analysis_service
from backend.services.dashboard_service import build_dashboard_meta
from backend.services.finnhub_news import finnhub_news_service
from backend.services.databento_gex import gex_service
from backend.services.market_data import market_data_service
from backend.services.instruments import get_instrument, instrument_registry
from backend.services.session_service import get_session_status
from backend.services.storage_service import storage_service
from backend.services.timeframes import aggregate_candles
from backend.services.trade_engine import trade_engine_service

router = APIRouter(prefix="/api")


def require_admin(x_admin_token: str | None = Header(default=None)):
    if settings.allow_public_admin:
        return
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Admin token required")


@router.get("/health")
def health():
    market = market_data_service.health()
    engine = trade_engine_service.snapshot()
    return {"status": "ok" if market.get("candle_count",0) else "degraded", "mode": market["mode"], "data_source": market["data_source"], "symbol": market.get("symbol"), "instrument": market.get("instrument"), "market": market, "gex": gex_service.health(), "session": get_session_status(), "engine": engine.model_dump(mode="json")}


@router.get("/session")
def session_status():
    return get_session_status()


@router.get("/instruments")
def instruments():
    return {"active_symbol": instrument_registry.active.symbol, "items": instrument_registry.list_public()}


@router.post("/market/symbol")
async def select_market_symbol(request: MarketSymbolRequest):
    try:
        profile = get_instrument(request.symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    previous = market_data_service.symbol
    market = await market_data_service.switch_symbol(profile.symbol)
    await gex_service.switch_symbol(profile.symbol)
    if previous != profile.symbol:
        trade_engine_service.reset_for_symbol(profile.symbol)
        claude_analysis_service.reset_cache()
    setup = await trade_engine_service.run_once()
    return {
        "changed": previous != profile.symbol,
        "symbol": profile.symbol,
        "instrument": profile.public_dict(),
        "market": market,
        "gex": gex_service.health(),
        "session": get_session_status(),
        "setup": setup,
    }


@router.get("/market/snapshot")
def market_snapshot(timeframe: int = Query(1, ge=1, le=240), limit: int = Query(1000, ge=50, le=2400)):
    candles = aggregate_candles(market_data_service.snapshot(limit=limit), timeframe)
    change, percent = market_data_service.price_change()
    return {"symbol": market_data_service.symbol, "instrument": market_data_service.health().get("instrument"), "price": market_data_service.current_price, "change": change, "change_percent": percent, "timeframe_minutes": timeframe, "data_source": market_data_service.data_source, "candles": candles}


@router.get("/dashboard")
def dashboard_data():
    setup = trade_engine_service.current_setup()
    if setup is None:
        raise HTTPException(503, "Trade engine is starting")
    return {"setup": setup, "meta": build_dashboard_meta(setup), "session": get_session_status(), "engine": trade_engine_service.snapshot()}


@router.get("/setup/current")
def current_setup():
    setup = trade_engine_service.current_setup()
    if setup is None: raise HTTPException(503, "Trade engine is starting")
    return setup


@router.get("/gex/summary")
def gex_summary():
    setup = trade_engine_service.current_setup()
    if setup is None: raise HTTPException(503, "Trade engine is starting")
    return setup.gex


@router.get("/confluence")
def confluence():
    setup = trade_engine_service.current_setup()
    if setup is None: raise HTTPException(503, "Trade engine is starting")
    return {"score": setup.confidence, "components": setup.confidence_components, "maximums": setup.confidence_maximums, "signals": setup.signals, "rationale": setup.rationale, "cluster": {"score": setup.cluster_score, "low": setup.cluster_low, "high": setup.cluster_high, "gex_level": setup.cluster_gex_level, "gex_type": setup.cluster_gex_type, "zone_timeframe": setup.selected_zone_timeframe}}


@router.get("/setups/history")
def setup_history(limit: int = Query(100, ge=1, le=500)):
    return storage_service.recent_setups(limit)


@router.get("/alerts")
def alerts(limit: int = Query(100, ge=1, le=500)):
    return storage_service.recent_alerts(limit)


@router.get("/positions")
def positions():
    setup = trade_engine_service.current_setup()
    if setup and setup.order_state in {"FILLED", "TP1_HIT"}:
        return [{"setup_id": setup.setup_id, "symbol": setup.symbol, "direction": setup.direction, "entry": setup.entry, "stop_loss": setup.stop_loss, "take_profit_1": setup.take_profit_1, "take_profit_2": setup.take_profit_2, "state": setup.order_state, "filled_at": setup.filled_at}]
    return []


@router.post("/backtest")
def backtest(request: BacktestRequest):
    return run_backtest(request)


@router.get("/settings")
def read_settings():
    profile = instrument_registry.active
    return {"data_provider": settings.data_provider, "simulated_mode": settings.simulated_mode, "active_symbol": profile.symbol, "supported_symbols": ", ".join(item["symbol"] for item in instrument_registry.list_public()), "dataset": settings.databento_dataset, "futures_symbol": profile.futures_continuous, "options_parent": profile.options_parent, "gex_source": profile.gex_source_label, "tick_size": profile.tick_size, "gex_refresh_seconds": settings.gex_refresh_seconds, "actionable_score": settings.setup_actionable_score, "expiry_minutes": settings.setup_expiry_minutes, "cluster_min_score": settings.cluster_min_score, "database": "postgresql/supabase" if settings.database_url.startswith(("postgres","postgresql")) else "sqlite", "admin_protected": not settings.allow_public_admin, "claude_analysis_enabled": claude_analysis_service.enabled, "claude_model": settings.anthropic_model, "finnhub_news_enabled": finnhub_news_service.enabled}


@router.get("/news")
def latest_news(limit: int = Query(8, ge=1, le=20), symbol: str | None = Query(default=None)):
    try:
        return {"items": finnhub_news_service.latest(limit, symbol=symbol), "status": finnhub_news_service.status(symbol=symbol)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/news/status")
def news_status(symbol: str | None = Query(default=None)):
    try:
        return finnhub_news_service.status(symbol=symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ai/status")
def ai_status():
    return claude_analysis_service.status()


@router.get("/ai/analysis/stream")
async def ai_analysis_stream(force: bool = Query(False)):
    return StreamingResponse(
        claude_analysis_service.stream(force=force),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/gex/refresh")
async def refresh_gex(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    refreshed = await gex_service.refresh()
    return {"refreshed": refreshed, "gex": gex_service.health()}


@router.post("/setup/reset")
def reset_setup(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token); trade_engine_service.reset(); return {"reset": True}
