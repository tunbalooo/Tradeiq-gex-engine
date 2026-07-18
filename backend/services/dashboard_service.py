from datetime import datetime

from backend.models.schemas import AlertItem, DashboardMeta, NewsItem, PerformanceSummary, TradeSetup
from backend.services.market_data import market_data_service


def build_dashboard_meta(setup: TradeSetup) -> DashboardMeta:
    direction_text = setup.direction.title()
    entry_text = f"{setup.entry:,.2f}" if setup.entry is not None else "—"
    tp_text = f"{setup.take_profit_1:,.2f}" if setup.take_profit_1 is not None else "—"
    flip_text = f"{setup.gex.gamma_flip:,.2f}"

    alerts = [
        AlertItem(
            time=setup.timestamp.astimezone().strftime("%H:%M:%S"),
            title=f"{direction_text} setup {setup.status.replace('_', ' ').title()}",
            detail=f"Confidence {setup.confidence:.0f}% · Entry {entry_text} · TP1 {tp_text}",
            severity="positive" if setup.confidence >= 70 else "warning",
        ),
        AlertItem(
            time=setup.timestamp.astimezone().strftime("%H:%M:%S"),
            title="GEX Update",
            detail=f"Gamma flip {flip_text} · Regime {setup.gex.regime.title()}",
            severity="info",
        ),
    ]

    if setup.signals.get("liquidity_sweep"):
        alerts.append(
            AlertItem(
                time=setup.timestamp.astimezone().strftime("%H:%M:%S"),
                title="Liquidity Sweep",
                detail="The structure engine detected a recent liquidity sweep.",
                severity="positive",
            )
        )
    if setup.signals.get("approaching_wall"):
        alerts.append(
            AlertItem(
                time=setup.timestamp.astimezone().strftime("%H:%M:%S"),
                title="Gamma Wall Nearby",
                detail="Price is approaching the directional GEX wall.",
                severity="warning",
            )
        )

    from backend.services.finnhub_calendar import get_calendar
    news = get_calendar()

    # Real performance computed from tracked paper-trade outcomes (TP/SL hits).
    from backend.services.trade_tracker import performance_summary
    performance = performance_summary()

    return DashboardMeta(
        overview=market_data_service.overview(),
        alerts=alerts[:4],
        news=news,
        performance=performance,
    )
