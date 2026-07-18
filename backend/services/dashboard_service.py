from backend.models.schemas import AlertItem, DashboardMeta, TradeSetup
from backend.services.finnhub_news import finnhub_news_service
from backend.services.market_data import market_data_service
from backend.services.storage_service import storage_service


def build_dashboard_meta(setup: TradeSetup) -> DashboardMeta:
    alerts = storage_service.recent_alerts(8)
    if not alerts:
        alerts = [AlertItem(time=setup.timestamp.astimezone().strftime("%H:%M:%S"), title="Engine Ready", detail=f"{setup.status.replace('_',' ').title()} · Confidence {setup.confidence:.0f}/100", severity="info")]
    news = finnhub_news_service.latest(8)
    return DashboardMeta(overview=market_data_service.overview(), alerts=alerts, news=news, performance=storage_service.performance())
