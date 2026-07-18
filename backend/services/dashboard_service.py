from backend.models.schemas import AlertItem, DashboardMeta, NewsItem, PerformanceSummary, TradeSetup
from backend.services.market_data import market_data_service


def build_dashboard_meta(setup: TradeSetup) -> DashboardMeta:
    direction_text = setup.direction.title()
    entry_text = f"{setup.entry:,.2f}" if setup.entry is not None else "—"
    tp_text = f"{setup.take_profit_1:,.2f}" if setup.take_profit_1 is not None else "—"
    flip_text = f"{setup.gex.gamma_flip:,.2f}"

    if setup.order_state == "PREVIEW_ONLY":
        title = f"{direction_text} preview — not armed"
        severity = "warning"
    else:
        title = f"{direction_text} {setup.order_state.replace('_', ' ').title()}"
        severity = "positive" if setup.order_state in {"WAITING_FOR_LIMIT", "FILLED", "TP1_HIT", "TP2_HIT"} else "warning"

    alerts = [
        AlertItem(
            time=setup.timestamp.astimezone().strftime("%H:%M:%S"),
            title=title,
            detail=f"Confidence {setup.confidence:.0f}/100 · Entry {entry_text} · TP1 {tp_text}",
            severity=severity,
        ),
        AlertItem(
            time=setup.timestamp.astimezone().strftime("%H:%M:%S"),
            title="GEX Update",
            detail=f"Gamma flip {flip_text} · Regime {setup.gex.regime.title()}",
            severity="info",
        ),
    ]

    if setup.signals.get("gex_ote_zone_cluster"):
        alerts.append(
            AlertItem(
                time=setup.timestamp.astimezone().strftime("%H:%M:%S"),
                title="Three-Way Cluster",
                detail=f"GEX + OTE + {setup.selected_zone_timeframe or ''} zone aligned near the proposed limit.",
                severity="positive",
            )
        )
    if setup.signals.get("liquidity_sweep"):
        alerts.append(
            AlertItem(
                time=setup.timestamp.astimezone().strftime("%H:%M:%S"),
                title="Directional Liquidity Sweep",
                detail="The sweep direction agrees with the proposed trade.",
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

    # Real performance computed from logged lifecycle outcomes (empty-safe).
    from backend.services.outcome_logger import performance_summary
    performance = performance_summary()

    return DashboardMeta(
        overview=market_data_service.overview(),
        alerts=alerts[:5],
        news=news,
        performance=performance,
    )
