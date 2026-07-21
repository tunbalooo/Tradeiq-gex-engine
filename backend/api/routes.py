from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.core.config import settings
from backend.models.schemas import BacktestRequest, MarketSymbolRequest
from backend.services.backtest_service import run_backtest
from backend.services.analytics_service import analytics_service
from backend.services.claude_analysis import claude_analysis_service
from backend.services.dashboard_service import build_dashboard_meta
from backend.services.decision_brain import decision_brain_service
from backend.services.finnhub_news import finnhub_news_service
from backend.services.finnhub_calendar import finnhub_calendar_service
from backend.services.databento_gex import gex_service
from backend.services.market_data import market_data_service
from backend.services.multi_market_monitor import multi_market_monitor_service
from backend.services.instruments import get_instrument, instrument_registry
from backend.services.session_service import get_session_status
from backend.services.setup_service import clear_fallback_gex_cache, current_gex_summary
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
    healthy = bool(market.get("candle_count", 0)) and (
        market.get("data_source") != "databento"
        or market.get("data_fresh")
        or market.get("stream_state") == "MARKET_CLOSED"
    )
    return {"status": "ok" if healthy else "degraded", "mode": market["mode"], "data_source": market["data_source"], "symbol": market.get("symbol"), "instrument": market.get("instrument"), "market": market, "gex": gex_service.health(), "session": get_session_status(), "engine": engine.model_dump(mode="json")}


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
    # Cached history makes the visual switch immediate; complete one deterministic
    # engine pass before returning so API clients always receive a coherent setup.
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


@router.get("/multi-market/opportunities")
def multi_market_opportunities():
    return {
        "items": multi_market_monitor_service.snapshot(),
        "status": multi_market_monitor_service.status(),
    }


@router.get("/multi-market/status")
def multi_market_status():
    return multi_market_monitor_service.status()


@router.post("/multi-market/scan")
async def scan_multi_market_now(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    items = await multi_market_monitor_service.scan_once()
    return {"items": items, "status": multi_market_monitor_service.status()}


@router.get("/market/snapshot")
def market_snapshot(timeframe: int = Query(1, ge=1, le=240), limit: int = Query(1000, ge=50, le=2400)):
    raw_candles = market_data_service.snapshot(limit=limit)
    candles = aggregate_candles(raw_candles, timeframe)
    change, percent = market_data_service.price_change()
    health = market_data_service.health()
    return {
        "symbol": market_data_service.symbol,
        "instrument": health.get("instrument"),
        "price": market_data_service.current_price if raw_candles else None,
        "change": change,
        "change_percent": percent,
        "timeframe_minutes": timeframe,
        "data_source": market_data_service.data_source,
        "raw_symbol": health.get("raw_symbol"),
        "futures_symbol": health.get("futures_symbol"),
        "history_ready": health.get("history_ready", bool(raw_candles)),
        "history_cached": health.get("history_cached", bool(raw_candles)),
        "history_source": health.get("history_source", market_data_service.data_source),
        "data_quality": health.get("data_quality", "READY"),
        "warming": health.get("warming", False),
        "stream_state": health.get("stream_state"),
        "data_fresh": health.get("data_fresh"),
        "last_record_at": health.get("last_record_at"),
        "last_record_age_seconds": health.get("last_record_age_seconds"),
        "last_candle_at": health.get("last_candle_at"),
        "last_candle_age_seconds": health.get("last_candle_age_seconds"),
        "candle_count": len(candles),
        "candles": candles,
    }


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
    if setup is not None:
        return setup.gex
    try:
        return current_gex_summary()
    except Exception as exc:
        raise HTTPException(503, f"GEX is still starting: {exc}") from exc


@router.get("/live-state")
def live_state():
    """Lightweight REST mirror of the market WebSocket payload.

    Browsers and installed PWAs use this endpoint while a proxy or network is
    preventing a WebSocket handshake. It keeps the chart, setup panel and GEX
    Analysis page current without pretending the socket is connected.
    """
    setup = trade_engine_service.current_setup()
    market = market_data_service.health()
    candles = market_data_service.snapshot(limit=1)
    try:
        gex = setup.gex if setup is not None else current_gex_summary()
    except Exception:
        gex = None
    try:
        meta = build_dashboard_meta(setup) if setup is not None else None
    except Exception:
        meta = None
    return {
        "type": "market_update",
        "transport": "rest",
        "candle": candles[-1] if candles else None,
        "setup": setup,
        "meta": meta,
        "market": market,
        "gex_summary": gex,
        "gex_health": gex_service.health(),
        "session": get_session_status(),
        "engine": trade_engine_service.snapshot(),
    }


@router.get("/confluence")
def confluence():
    setup = trade_engine_service.current_setup()
    if setup is None: raise HTTPException(503, "Trade engine is starting")
    return {
        "score": setup.confidence,
        "grade": setup.confidence_grade,
        "institutional_components": setup.institutional_confidence_components,
        "institutional_maximums": setup.institutional_confidence_maximums,
        "components": setup.confidence_components,
        "maximums": setup.confidence_maximums,
        "signals": setup.signals,
        "rationale": setup.rationale,
        "primary_entry_model": setup.primary_entry_model,
        "entry_models": setup.entry_model_scores,
        "cluster": {"score": setup.cluster_score, "low": setup.cluster_low, "high": setup.cluster_high, "gex_level": setup.cluster_gex_level, "gex_type": setup.cluster_gex_type, "zone_timeframe": setup.selected_zone_timeframe},
    }


@router.get("/decision-brain")
def decision_brain():
    return decision_brain_service.snapshot(trade_engine_service.current_setup())


@router.get("/entry-models")
def entry_models():
    setup = trade_engine_service.current_setup()
    if setup is None:
        raise HTTPException(503, "Trade engine is starting")
    return {
        "setup_id": setup.setup_id,
        "primary": setup.primary_entry_model,
        "primary_score": setup.primary_model_score,
        "alternatives": setup.alternative_entry_models,
        "models": setup.entry_model_scores,
    }


@router.get("/analytics/summary")
def analytics_summary(limit: int = Query(1000, ge=1, le=5000)):
    return analytics_service.summary(limit)


@router.get("/setups/history")
def setup_history(limit: int = Query(100, ge=1, le=500)):
    return storage_service.recent_setups(limit)


@router.get("/setups/{setup_id}/timeline")
def setup_timeline(setup_id: str, limit: int = Query(100, ge=1, le=500)):
    return {"setup_id": setup_id, "events": storage_service.setup_timeline(setup_id, limit)}


@router.get("/alerts")
def alerts(limit: int = Query(100, ge=1, le=500)):
    return storage_service.recent_alerts(limit)


@router.get("/positions")
def positions():
    setup = trade_engine_service.current_setup()
    if setup and setup.order_state in {"FILLED", "TP1_HIT"}:
        return [{"setup_id": setup.setup_id, "symbol": setup.symbol, "direction": setup.direction, "entry": setup.entry, "stop_loss": setup.stop_loss, "active_stop_loss": setup.active_stop_loss, "take_profit_1": setup.take_profit_1, "take_profit_2": setup.take_profit_2, "state": setup.order_state, "management_state": setup.management_state, "primary_entry_model": setup.primary_entry_model, "filled_at": setup.filled_at}]
    return []


@router.post("/backtest")
def backtest(request: BacktestRequest):
    return run_backtest(request)


@router.get("/settings")
def read_settings():
    profile = instrument_registry.active
    return {"data_provider": settings.data_provider, "simulated_mode": settings.simulated_mode, "active_symbol": profile.symbol, "supported_symbols": ", ".join(item["symbol"] for item in instrument_registry.list_public()), "dataset": settings.databento_dataset, "futures_symbol": profile.futures_continuous, "options_parent": profile.options_parent, "gex_source": profile.gex_source_label, "tick_size": profile.tick_size, "gex_refresh_seconds": settings.gex_refresh_seconds, "actionable_score": settings.setup_actionable_score, "expiry_minutes": settings.setup_expiry_minutes, "cluster_min_score": settings.cluster_min_score, "entry_model_min_score": settings.entry_model_min_score, "move_stop_to_breakeven_after_tp1": settings.move_stop_to_breakeven_after_tp1, "partial_exit_percent": settings.partial_exit_percent, "multi_market_alerts_enabled": settings.multi_market_alerts_enabled, "multi_market_symbols": settings.multi_market_symbols, "multi_market_scan_seconds": settings.multi_market_scan_seconds, "multi_market_history_refresh_seconds": settings.multi_market_history_refresh_seconds, "multi_market_max_data_age_seconds": settings.multi_market_max_data_age_seconds, "multi_market_min_model_score": settings.multi_market_min_model_score, "databento_live_stale_seconds": settings.databento_live_stale_seconds, "databento_live_watchdog_seconds": settings.databento_live_watchdog_seconds, "databento_reconnect_initial_seconds": settings.databento_reconnect_initial_seconds, "databento_reconnect_max_seconds": settings.databento_reconnect_max_seconds, "database": "postgresql/supabase" if settings.database_url.startswith(("postgres","postgresql")) else "sqlite", "admin_protected": not settings.allow_public_admin, "claude_analysis_enabled": claude_analysis_service.enabled, "claude_model": settings.anthropic_model, "finnhub_news_enabled": finnhub_news_service.enabled, "finnhub_economic_calendar": finnhub_calendar_service.status()}


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


@router.get("/economic-calendar")
def economic_calendar(limit: int = Query(10, ge=1, le=30), days: int = Query(7, ge=1, le=30)):
    return {"items": finnhub_calendar_service.latest(limit=limit, days=days), "status": finnhub_calendar_service.status()}


@router.get("/economic-calendar/status")
def economic_calendar_status():
    return finnhub_calendar_service.status()


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
    if not refreshed:
        clear_fallback_gex_cache(market_data_service.symbol)
    return {"refreshed": refreshed, "fallback_cache_cleared": not refreshed, "gex": gex_service.health()}


@router.post("/setup/reset")
def reset_setup(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token); trade_engine_service.reset(); return {"reset": True}
