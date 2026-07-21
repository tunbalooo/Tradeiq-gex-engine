from backend.models.schemas import AlertItem, DashboardMeta, TradeSetup
from backend.core.time_utils import ensure_utc
from backend.services.finnhub_news import finnhub_news_service
from backend.services.market_data import market_data_service
from backend.services.storage_service import storage_service


def build_dashboard_meta(setup: TradeSetup) -> DashboardMeta:
    alerts = storage_service.recent_alerts(8)
    if not alerts:
        created_at = ensure_utc(setup.timestamp)
        alerts = [AlertItem(
            time=created_at.strftime("%H:%M:%S UTC") if created_at else "—",
            title="Engine Ready",
            detail=f"{setup.status.replace('_',' ').title()} · Confidence {setup.confidence:.0f}/100",
            severity="info",
            created_at=created_at,
        )]
    news = finnhub_news_service.latest(8)
    return DashboardMeta(overview=market_data_service.overview(), alerts=alerts, news=news, performance=storage_service.performance())
