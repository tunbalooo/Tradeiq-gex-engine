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

    news = [
        NewsItem(time="10:00", event="US JOLTS Job Openings", impact="High"),
        NewsItem(time="10:30", event="Crude Oil Inventories", impact="Med"),
        NewsItem(time="11:00", event="Fed Chair / Member Speech", impact="High"),
        NewsItem(time="14:00", event="FOMC Member Speech", impact="Med"),
    ]

    # Development-only performance sample. The UI clearly marks the app as simulated.
    equity = [
        0, 140, 95, 260, 420, 355, 610, 780, 710, 980,
        1210, 1140, 1450, 1590, 1510, 1880, 2050, 1970, 2360, 2580,
        2490, 2870, 3010, 2920, 3260, 3420,
    ]
    performance = PerformanceSummary(
        win_rate=68.0,
        trades=22,
        average_r=1.72,
        profit_factor=2.31,
        net_pnl=3420.0,
        equity_curve=equity,
        simulated=True,
    )

    return DashboardMeta(
        overview=market_data_service.overview(),
        alerts=alerts[:4],
        news=news,
        performance=performance,
    )
