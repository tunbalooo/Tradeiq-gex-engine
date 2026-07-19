# TradeIQ v1.7 — Upcoming Economic Calendar

- Separates **upcoming economic events** from ordinary market headlines.
- Upcoming events use the Finnhub Economic Calendar scheduled release timestamp.
- Mobile and desktop show weekday, full date, scheduled ET time, impact, forecast and previous value.
- Market-headline timestamps remain correctly labelled as publication times.
- Adds `/api/economic-calendar` and `/api/economic-calendar/status`.
- Gracefully explains when the connected Finnhub plan does not include the premium economic calendar.
- No effect on confidence, setup status, session gating or order arming.
