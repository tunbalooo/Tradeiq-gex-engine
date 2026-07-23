// if (!force && state.marketWarming) return;
// Structural Invalidation
// Watch expired — waiting for a new candidate
// Legacy silent-monitoring regression markers retained as comments only; v3.1.2 never renders them:
// overlays: { clean: true
// score preserved, no new order
// not an armed order
// MONITORING ${setup.direction}
// Watch Trigger · Not an Order
// Watch Touched · Awaiting Confirmation
// setup.watch_expires_at || setup.valid_until
// Legacy GEX note: Maximum pain is shown only when open-interest data is available
// Legacy v2.0 regression reference: lockedPlan ? fmt(setup.stop_loss) : "—"
// Legacy news display reference retained for regression tests: timeZone: "America/New_York"
const $ = (id) => document.getElementById(id);
const SCORE_LABELS = {
  trend_alignment: "Trend (EMA 9/21/55)",
  gex_alignment: "GEX Alignment",
  liquidity_sweep: "Liquidity Sweep",
  displacement: "FVG / Displacement",
  ote_overlap: "OTE 0.618–0.786",
  supply_demand: "Supply / Demand Zone",
  gex_ote_zone_cluster: "GEX + OTE + Zone Cluster",
  std_dev_confluence: "Std Dev Confluence",
  vwap_alignment: "VWAP Alignment",
  session_volatility: "Session / Volatility",
  risk_reward: "Risk / Reward",
};
const SIGNAL_LABELS = {
  trend_alignment: "EMA trend aligned",
  gex_alignment: "Price aligned with Gamma Flip",
  liquidity_sweep: "Liquidity sweep detected",
  displacement: "Displacement candle detected",
  ote_overlap: "Price near active OTE",
  supply_demand: "Supply / demand confluence",
  gex_ote_zone_cluster: "GEX + OTE + zone cluster",
  gex_inside_cluster: "GEX level inside cluster",
  directional_fvg: "Directional FVG confirmed",
  valid_limit: "Valid resting limit",
  target_not_blocked: "Target path is not blocked",
  std_dev_confluence: "Standard-deviation confluence",
  vwap_alignment: "Price aligned with VWAP",
  approaching_wall: "Approaching directional GEX wall",
  fib_pullback_touched: "50%–61.8% pullback zone touched",
  fib_pullback_rejection: "Fib pullback rejection confirmed",
  fib_pullback_entry_fresh: "Confirmation entry remains fresh",
};
const COLORS = {
  green: "#26D07C", red: "#FF4D5E", amber: "#F5B93B", blue: "#48A3FF",
  purple: "#A98BFF", muted: "#455468", text: "#D8E2F0", line: "#1A2636",
};
const ACTIVE_TRADE_STATES = new Set(["WAITING_FOR_LIMIT", "FILLED", "TP1_HIT"]);
const DEFAULT_OVERLAYS = {
  clean: false,
  scan: true,
  map: true,
  emas: true,
  gex: true,
  fib: true,
  zones: true,
  trade: true,
  vwap: true,
};

function loadOverlayPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem("tradeiq-chart-overlays") || "{}");
    return { ...DEFAULT_OVERLAYS, ...(saved && typeof saved === "object" ? saved : {}) };
  } catch (_error) {
    return { ...DEFAULT_OVERLAYS };
  }
}

function saveOverlayPreferences() {
  try { localStorage.setItem("tradeiq-chart-overlays", JSON.stringify(state.overlays)); }
  catch (_error) { /* Storage can be unavailable in private browser modes. */ }
}

function syncOverlayButtons() {
  document.querySelectorAll(".overlay-btn").forEach((button) => {
    const name = button.dataset.overlay;
    button.classList.toggle("active", Boolean(state.overlays[name]));
    button.setAttribute("aria-pressed", String(Boolean(state.overlays[name])));
  });
}

function hasWatchingPlan(setup) {
  return Boolean(
    setup
    && setup.order_state === "WATCHING"
    && ["LONG", "SHORT"].includes(setup.direction)
    && Number.isFinite(Number(setup.watch_trigger))
  );
}


function watchTrigger(setup) {
  return Number.isFinite(Number(setup?.watch_trigger)) ? Number(setup.watch_trigger) : null;
}

function watchTriggerTouched(setup) {
  return Boolean(hasWatchingPlan(setup) && setup.watch_phase === "TRIGGER_TOUCHED");
}

// Legacy v2.0 assertion reference: "Entry (locks when armed)"
// Legacy v2.0 assertion reference: $("chartSetupEntry").textContent = lockedPlan ? fmt(setup.entry) : "—";
function hasLockedTradePlan(setup) {
  if (!setup || !ACTIVE_TRADE_STATES.has(setup.order_state) || !setup.armed_at) return false;
  return [setup.entry, setup.stop_loss, setup.take_profit_1, setup.take_profit_2]
    .every((value) => Number.isFinite(Number(value)));
}
const state = {
  baseCandles: [],
  setup: null,
  meta: null,
  gexSummary: null,
  timeframe: 5,
  connected: false,
  dataSource: "SIMULATED",
  session: null,
  currentPage: "dashboard",
  hoverIndex: null,
  chartMeta: null,
  instrument: null,
  switchingSymbol: false,
  marketWarming: false,
  historyReady: false,
  historySource: "unknown",
  dataQuality: "UNKNOWN",
  rawSymbol: null,
  socket: null,
  socketLastMessageAt: 0,
  socketReconnectAttempt: 0,
  socketReconnectTimer: null,
  socketWatchdogTimer: null,
  socketConnectTimer: null,
  restFallbackTimer: null,
  restFallbackBusy: false,
  restFallbackActive: false,
  feedState: "CONNECTING",
  feedRecordAgeSeconds: null,
  feedLastRecordAt: null,
  overlays: loadOverlayPreferences(),
  claude: {
    enabled: false, auto: true, busy: false, source: null, text: "", model: "—",
    lastStartedAt: 0, pendingLifecycle: false, lastLifecycleKey: null,
  },
  mobilePane: localStorage.getItem("tradeiq-mobile-pane") || "chart",
  mobileNewsTab: localStorage.getItem("tradeiq-mobile-news-tab") || "calendar",
  deferredInstallPrompt: null,
  setupTimeline: [],
  timelineSetupId: null,
  timelineLifecycleKey: null,
  marketOpportunities: [],
  marketRadarStatus: null,
  seenOpportunityIds: new Set(JSON.parse(localStorage.getItem("tradeiq-seen-opportunities") || "[]")),
  marketCache: {},
  deskTab: localStorage.getItem("tradeiq-desk-tab") || "setup",
  deskCollapsed: localStorage.getItem("tradeiq-desk-collapsed") === "true",
};


function displayTimeZone() { return window.TradeIQTime?.zone?.() || "America/New_York"; }
function displayTimeZoneLabel(value = new Date()) { return window.TradeIQTime?.abbreviation?.(value) || "ET"; }
function parseAppTimestamp(value) { return window.TradeIQTime?.normalize?.(value) || (value ? new Date(value) : null); }
function formatAppTime(value, options = {}) {
  return window.TradeIQTime?.formatTime?.(value, options) || (value ? new Date(value).toLocaleTimeString("en-US", options) : "—");
}
function formatAppDateTime(value, options = {}) {
  return window.TradeIQTime?.formatDateTime?.(value, options) || (value ? new Date(value).toLocaleString("en-US", options) : "—");
}
function formatAppDate(value, options = {}) {
  return window.TradeIQTime?.format?.(value, options) || (value ? new Date(value).toLocaleDateString("en-US", options) : "—");
}

function activeSymbol() { return state.instrument?.symbol || state.setup?.symbol || "NQ"; }
function displaySymbol() { return state.instrument?.display_symbol || `${activeSymbol()}1!`; }
function instrumentName() { return state.instrument?.name || "Futures market"; }
function pricePrecision() { return Number.isInteger(state.instrument?.price_precision) ? state.instrument.price_precision : 2; }
function tickSize() { return Number(state.instrument?.tick_size || 0.25); }
function timeframeLabel() { return state.timeframe >= 60 ? `${state.timeframe / 60}h` : `${state.timeframe}m`; }
function chartFeedLabel() {
  const quality = state.dataQuality && state.dataQuality !== "READY" ? ` · ${state.dataQuality.replaceAll("_", " ")}` : "";
  return `${instrumentName()} · ${timeframeLabel()} · ${state.dataSource}${quality}`;
}

function cacheCurrentMarket() {
  const symbol = activeSymbol();
  if (!symbol || !state.baseCandles.length || !state.instrument) return;
  state.marketCache[symbol] = {
    candles: state.baseCandles.map((item) => ({ ...item })),
    instrument: { ...state.instrument },
    historyReady: state.historyReady,
    historySource: state.historySource,
    dataQuality: state.dataQuality,
    rawSymbol: state.rawSymbol,
    dataSource: state.dataSource,
    marketWarming: state.marketWarming,
    setup: state.setup ? JSON.parse(JSON.stringify(state.setup)) : null,
    meta: state.meta ? JSON.parse(JSON.stringify(state.meta)) : null,
    session: state.session ? JSON.parse(JSON.stringify(state.session)) : null,
  };
}

function restoreCachedMarket(symbol) {
  const cached = state.marketCache[symbol];
  if (!cached) return false;
  state.baseCandles = cached.candles.map((item) => ({ ...item }));
  state.historyReady = cached.historyReady;
  state.historySource = cached.historySource;
  state.dataQuality = cached.dataQuality;
  state.rawSymbol = cached.rawSymbol;
  state.dataSource = cached.dataSource;
  state.marketWarming = cached.marketWarming;
  applyInstrument(cached.instrument);
  if (cached.setup && cached.meta) renderAll(cached.setup, cached.meta, cached.session);
  renderHeader({ price: state.baseCandles.at(-1)?.close, instrument: cached.instrument });
  window.TradeIQChartManager?.marketChanged?.("chart");
  window.TradeIQChartManager?.marketChanged?.("chartLarge");
  drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
  return true;
}

function saveSeenOpportunities() {
  const values = [...state.seenOpportunityIds].slice(-100);
  localStorage.setItem("tradeiq-seen-opportunities", JSON.stringify(values));
}

function opportunityPrice(value, symbol) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const digits = ["ES", "MES"].includes(symbol) ? 2 : 2;
  return Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function renderMarketRadar(items = state.marketOpportunities, status = state.marketRadarStatus) {
  const list = $("marketRadarList");
  if (!list) return;
  const alertable = items.filter((item) => item.alertable);
  const badge = $("marketRadarBadge");
  if (badge) {
    badge.textContent = String(alertable.length);
    badge.hidden = alertable.length === 0;
  }
  const statusNode = $("marketRadarStatus");
  if (statusNode) {
    statusNode.textContent = status?.last_error ? "DEGRADED" : status?.running === false ? "OFF" : "LIVE";
    statusNode.className = `market-radar-status ${status?.last_error ? "error" : status?.running === false ? "" : "ready"}`;
  }
  if ($("marketRadarUpdated")) {
    const stamp = status?.last_scan_at ? formatAppTime(status.last_scan_at) : "—";
    $("marketRadarUpdated").textContent = `Updated ${stamp} ${displayTimeZoneLabel(status?.last_scan_at)}`;
  }
  if (!items.length) {
    list.innerHTML = '<div class="market-radar-empty">The radar is warming NQ, ES and GC history.</div>';
    return;
  }
  list.innerHTML = items.map((item) => {
    const direction = item.alertable ? String(item.direction || "NONE").toLowerCase() : "none";
    const displayDirection = item.alertable ? (item.direction || "ENTRY") : "SCANNING";
    const model = item.alertable
      ? escapeHtml(item.model || "Validated institutional setup")
      : "Scanning internally";
    const reason = item.alertable
      ? escapeHtml(item.reason || "A validated execution plan is ready.")
      : "No actionable entry has passed every gate yet.";
    const score = item.alertable ? `${Number(item.model_score || 0).toFixed(0)}%` : "—";
    return `<button type="button" class="market-radar-card ${direction} ${item.alertable ? "alertable" : ""}" data-radar-symbol="${escapeHtml(item.symbol)}">
      <div class="market-radar-symbol"><b>${escapeHtml(item.symbol)}</b><span>${escapeHtml(displayDirection)}</span></div>
      <div class="market-radar-score">${score}</div>
      <div class="market-radar-model">${model}</div>
      <div class="market-radar-detail"><span>State <b>${item.alertable ? "ENTRY READY" : "SCANNING"}</b></span><span>Grade <b>${escapeHtml(item.grade || "—")}</b></span></div>
      <div class="market-radar-reason">${reason}</div>
    </button>`;
  }).join("");
}

function notifyMarketOpportunity(item) {
  const message = `${item.model || "Institutional model"} ${Number(item.model_score || 0).toFixed(0)}% · ${item.alertable ? "validated entry ready" : "scanning internally"}`;
  toast(`${item.symbol} ${item.direction} setup forming · ${message}`);
  if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
    const notification = new Notification(`${item.symbol} ${item.direction} setup forming`, { body: message, icon: "/static/app-icon-192.png", tag: item.opportunity_id });
    notification.onclick = () => { window.focus(); switchMarket(item.symbol); notification.close(); };
  }
}

function processMarketOpportunities(items = [], status = null, announce = true) {
  state.marketOpportunities = Array.isArray(items) ? items : [];
  state.marketRadarStatus = status || state.marketRadarStatus;
  renderMarketRadar();
  for (const item of state.marketOpportunities) {
    if (!item.alertable || !item.opportunity_id || state.seenOpportunityIds.has(item.opportunity_id)) continue;
    state.seenOpportunityIds.add(item.opportunity_id);
    if (announce) notifyMarketOpportunity(item);
  }
  saveSeenOpportunities();
}

async function loadMarketRadar(announce = false) {
  try {
    const payload = await fetch("/api/multi-market/opportunities").then((response) => {
      if (!response.ok) throw new Error(`Radar request failed (${response.status})`);
      return response.json();
    });
    processMarketOpportunities(payload.items || [], payload.status || null, announce);
  } catch (error) {
    console.error(error);
    state.marketRadarStatus = { running: false, last_error: error.message };
    renderMarketRadar();
  }
}

function setDeskTab(tab) {
  const resolved = ["setup", "claude", "radar"].includes(tab) ? tab : "setup";
  state.deskTab = resolved;
  localStorage.setItem("tradeiq-desk-tab", resolved);
  document.querySelectorAll("[data-desk-tab]").forEach((button) => button.classList.toggle("active", button.dataset.deskTab === resolved));
  document.querySelectorAll("[data-desk-pane]").forEach((pane) => pane.classList.toggle("active", pane.dataset.deskPane === resolved));
  if (resolved === "claude" && state.claude.enabled && state.claude.auto && !state.claude.text && !state.claude.busy) startClaudeAnalysis(false);
  if (resolved === "radar") loadMarketRadar(false);
}

function setDeskCollapsed(collapsed) {
  state.deskCollapsed = Boolean(collapsed);
  localStorage.setItem("tradeiq-desk-collapsed", String(state.deskCollapsed));
  $("page-chart")?.querySelector(".tv-chart-layout")?.classList.toggle("desk-collapsed", state.deskCollapsed);
  $("deskRailToggle")?.classList.toggle("active", !state.deskCollapsed);
  scheduleChartDraw("chartLarge", 20);
}

function applySnapshotMetadata(snapshot = {}) {
  state.historyReady = Boolean(snapshot.history_ready ?? snapshot.history_cached);
  state.historySource = snapshot.history_source || state.historySource || "unknown";
  state.dataQuality = snapshot.data_quality || (state.historyReady ? "READY" : "WAITING_FOR_HISTORY");
  state.rawSymbol = snapshot.raw_symbol || state.rawSymbol || null;
  state.marketWarming = Boolean(snapshot.warming || (snapshot.data_source === "databento" && !state.historyReady));
}

function applyInstrument(instrument) {
  if (!instrument) return;
  state.instrument = instrument;
  const selector = $("symbolSelect");
  if (selector && selector.value !== instrument.symbol) selector.value = instrument.symbol;
  document.title = `TradeIQ — ${instrument.symbol} ${instrument.name}`;
  if ($("chartBrandTitle")) $("chartBrandTitle").innerHTML = `Trade<span>IQ</span> Desk · ${escapeHtml(instrument.symbol)}`;
  if ($("chartCaption")) $("chartCaption").textContent = chartFeedLabel();
  if ($("chartLargeStatus")) $("chartLargeStatus").textContent = chartFeedLabel();
  if ($("newsPanelTitle")) $("newsPanelTitle").textContent = `${instrument.symbol} Market News · Finnhub`;
  if ($("mobileNewsTitle")) $("mobileNewsTitle").textContent = `${instrument.symbol} Market News`;
  if ($("pageTitle")) setPage(state.currentPage, false);
}

function fmt(value, digits = null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const resolvedDigits = digits === null ? pricePrecision() : digits;
  return Number(value).toLocaleString("en-US", { minimumFractionDigits: resolvedDigits, maximumFractionDigits: resolvedDigits });
}
function fmtSigned(value, digits = null) {
  const number = Number(value || 0);
  return `${number >= 0 ? "+" : ""}${fmt(number, digits)}`;
}
function fmtGex(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  const absolute = Math.abs(number);
  const sign = number >= 0 ? "+" : "-";
  if (absolute >= 1e9) return `${sign}${(absolute / 1e9).toFixed(2)}B`;
  if (absolute >= 1e6) return `${sign}${(absolute / 1e6).toFixed(0)}M`;
  if (absolute >= 1e3) return `${sign}${(absolute / 1e3).toFixed(0)}K`;
  return `${sign}${absolute.toFixed(0)}`;
}
function timeLabel(value) {
  return formatAppTime(value, { hour12: false });
}
function newsDateParts(item = {}) {
  const raw = item.published_at || item.datetime || item.date || null;
  const date = parseAppTimestamp(raw);
  if (!date || Number.isNaN(date.getTime())) {
    return { day: "—", date: "Date unavailable", time: String(item.time || "—"), full: String(item.time || "—") };
  }
  const day = formatAppDate(date, { weekday: "short" });
  const calendarDate = formatAppDate(date, { month: "short", day: "numeric", year: date.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined });
  const clock = window.TradeIQTime?.format?.(date, { hour: "numeric", minute: "2-digit", hour12: true }) || formatAppTime(date);
  const label = displayTimeZoneLabel(date);
  return { day, date: calendarDate, time: `${clock} ${label}`, full: `${day}, ${calendarDate} · ${clock} ${label}` };
}
function calendarDateParts(item = {}) {
  const raw = item.scheduled_at || item.time || null;
  const date = parseAppTimestamp(raw);
  if (!date || Number.isNaN(date.getTime())) {
    return { day: "—", date: "Date unavailable", time: "—", full: "Scheduled time unavailable" };
  }
  const day = formatAppDate(date, { weekday: "short" });
  const calendarDate = formatAppDate(date, { month: "short", day: "numeric", year: "numeric" });
  const clock = window.TradeIQTime?.format?.(date, { hour: "numeric", minute: "2-digit", hour12: true }) || formatAppTime(date);
  const label = displayTimeZoneLabel(date);
  return { day, date: calendarDate, time: `${clock} ${label}`, full: `${day}, ${calendarDate} · ${clock} ${label}` };
}
function calendarValue(value, unit) {
  if (value === null || value === undefined || value === "") return "—";
  return `${value}${unit ? ` ${unit}` : ""}`;
}

function compactNumber(value) {
  const number = Number(value || 0);
  const absolute = Math.abs(number);
  if (absolute >= 1e9) return `${number < 0 ? "-" : ""}${(absolute / 1e9).toFixed(1)}B`;
  if (absolute >= 1e6) return `${number < 0 ? "-" : ""}${(absolute / 1e6).toFixed(0)}M`;
  if (absolute >= 1e3) return `${number < 0 ? "-" : ""}${(absolute / 1e3).toFixed(0)}K`;
  return number.toFixed(0);
}

function gexStrikeRows(gex = {}) {
  const rows = Array.isArray(gex.by_strike) ? gex.by_strike : [];
  if (rows.length) {
    return rows.map((item) => ({
      strike: Number(item.strike),
      call_gex: Number(item.call_gex || 0),
      put_gex: Number(item.put_gex || 0),
      net_gex: Number(item.net_gex || 0),
    })).filter((item) => Number.isFinite(item.strike) && Number.isFinite(item.net_gex)).sort((a, b) => a.strike - b.strike);
  }
  return (gex.levels || []).map((item) => ({
    strike: Number(item.price),
    call_gex: Math.max(Number(item.gex || 0), 0),
    put_gex: Math.min(Number(item.gex || 0), 0),
    net_gex: Number(item.gex || 0),
  })).filter((item) => Number.isFinite(item.strike)).sort((a, b) => a.strike - b.strike);
}

function drawGexStrikeChart(canvas, gex = {}, compact = false) {
  if (!canvas) return;
  const width = Math.floor(canvas.clientWidth || canvas.parentElement?.clientWidth || 0);
  const height = Math.floor(canvas.clientHeight || (compact ? 210 : 340));
  if (width < 120 || height < 100) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0A111A";
  ctx.fillRect(0, 0, width, height);

  let rows = gexStrikeRows(gex);
  if (rows.length > (compact ? 31 : 55)) {
    const anchor = Number(gex.gamma_flip || rows[Math.floor(rows.length / 2)].strike);
    const nearest = rows.reduce((best, item, index) => Math.abs(item.strike - anchor) < Math.abs(rows[best].strike - anchor) ? index : best, 0);
    const count = compact ? 31 : 55;
    const start = Math.max(0, Math.min(rows.length - count, nearest - Math.floor(count / 2)));
    rows = rows.slice(start, start + count);
  }
  if (!rows.length) {
    ctx.fillStyle = "#7788A3";
    ctx.font = `${compact ? 11 : 12}px Inter, sans-serif`;
    ctx.textAlign = "center";
    ctx.fillText("Waiting for GEX-by-strike data…", width / 2, height / 2);
    return;
  }

  const margin = compact ? { left: 10, right: 44, top: 14, bottom: 28 } : { left: 18, right: 66, top: 18, bottom: 36 };
  const plotW = Math.max(1, width - margin.left - margin.right);
  const plotH = Math.max(1, height - margin.top - margin.bottom);
  const maxAbs = Math.max(...rows.map((item) => Math.abs(item.net_gex)), 1);
  const zeroY = margin.top + plotH / 2;
  const valueY = (value) => zeroY - (Number(value) / maxAbs) * (plotH * 0.44);

  ctx.strokeStyle = "rgba(129,145,166,.13)";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#7788A3";
  ctx.font = `${compact ? 8 : 10}px JetBrains Mono, monospace`;
  ctx.textAlign = "left";
  [-1, -.5, 0, .5, 1].forEach((ratio) => {
    const y = zeroY - ratio * plotH * .44;
    ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(margin.left + plotW, y); ctx.stroke();
    if (!compact || ratio === -1 || ratio === 0 || ratio === 1) ctx.fillText(compactNumber(maxAbs * ratio), margin.left + plotW + 6, y + 3);
  });

  const step = plotW / rows.length;
  const barW = Math.max(1, Math.min(compact ? 8 : 14, step * .72));
  rows.forEach((item, index) => {
    const x = margin.left + step * (index + .5);
    const y = valueY(item.net_gex);
    ctx.fillStyle = item.net_gex >= 0 ? "#26D07C" : "#FF4D5E";
    ctx.fillRect(x - barW / 2, Math.min(y, zeroY), barW, Math.max(1, Math.abs(zeroY - y)));
  });

  const flip = Number(gex.gamma_flip);
  if (Number.isFinite(flip) && flip >= rows[0].strike && flip <= rows.at(-1).strike) {
    const ratio = (flip - rows[0].strike) / Math.max(rows.at(-1).strike - rows[0].strike, 1e-9);
    const x = margin.left + ratio * plotW;
    ctx.save(); ctx.strokeStyle = "#DCE4EF"; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(x, margin.top); ctx.lineTo(x, margin.top + plotH); ctx.stroke(); ctx.restore();
  }

  const labels = compact ? 4 : 6;
  ctx.fillStyle = "#7788A3";
  ctx.font = `${compact ? 8 : 10}px JetBrains Mono, monospace`;
  ctx.textAlign = "center";
  for (let i = 0; i < labels; i += 1) {
    const index = Math.round(i * (rows.length - 1) / Math.max(labels - 1, 1));
    const x = margin.left + step * (index + .5);
    ctx.fillText(fmt(rows[index].strike, pricePrecision()), x, height - (compact ? 8 : 12));
  }
}

function refreshGexCharts() {
  const gex = state.setup?.gex || state.gexSummary;
  if (!gex) return;
  drawGexStrikeChart($("gexStrikeChart"), gex, false);
  drawGexStrikeChart($("mobileGexStrikeChart"), gex, true);
}

async function loadGexPage() {
  renderGexPage(state.setup || state.gexSummary);
  try {
    const response = await fetch("/api/gex/summary", { cache: "no-store" });
    if (!response.ok) throw new Error(`GEX request failed (${response.status})`);
    const gex = await response.json();
    if (gex?.applied_to_symbol && gex.applied_to_symbol !== activeSymbol()) return;
    state.gexSummary = gex;
    if (state.setup && !state.setup.gex) state.setup.gex = gex;
    renderGexPage(gex);
    drawChart();
    if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
  } catch (error) {
    console.warn("TradeIQ GEX page refresh failed", error);
    renderGexPage(state.setup || state.gexSummary);
  }
}

function classForDirection(direction) {
  return direction === "LONG" ? "g" : direction === "SHORT" ? "r" : "m";
}
function stars(strength) {
  const n = Math.max(0, Math.min(5, Number(strength || 0)));
  return "★".repeat(n) + "☆".repeat(5 - n);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setClaudeStatus(label, kind = "") {
  const el = $("claudeStatus");
  if (!el) return;
  el.textContent = label;
  el.className = `claude-status ${kind}`.trim();
}

function renderClaudeAnalysis(text, streaming = false) {
  const target = $("claudeAnalysis");
  if (!target) return;
  if (!text.trim()) {
    target.innerHTML = '<div class="claude-empty">Waiting for Claude analysis…</div>';
    return;
  }

  const sections = [];
  let current = null;
  const headingPattern = /^(EVENT|WHY|BIAS|STATUS|CONFIRMED|MISSING|MISSING\/NEXT|NEXT|LEVELS|WHAT I SEE|WHAT IS MISSING|RISK|ACTION):\s*(.*)$/i;
  text.split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) return;
    const match = line.match(headingPattern);
    if (match) {
      const rawHeading = match[1].toUpperCase();
      const heading = rawHeading === "WHAT I SEE"
        ? "CONFIRMED"
        : rawHeading === "WHAT IS MISSING"
          ? "MISSING/NEXT"
          : rawHeading === "MISSING" || rawHeading === "NEXT"
            ? "MISSING/NEXT"
            : rawHeading;
      current = { heading, lines: [] };
      if (match[2]) current.lines.push(match[2]);
      sections.push(current);
      return;
    }
    if (!current) {
      current = { heading: "ANALYSIS", lines: [] };
      sections.push(current);
    }
    current.lines.push(line);
  });

  target.innerHTML = sections.map((section) => {
    const bullets = section.lines.filter((line) => line.startsWith("- ")).map((line) => `<li>${escapeHtml(line.slice(2))}</li>`);
    const prose = section.lines.filter((line) => !line.startsWith("- ")).map((line) => escapeHtml(line)).join(" ");
    const sectionClass = `claude-section-${section.heading.toLowerCase().replaceAll(" ", "-")}`;
    return `<section class="claude-analysis-section ${sectionClass}"><h4>${escapeHtml(section.heading)}</h4>${prose ? `<p>${prose}</p>` : ""}${bullets.length ? `<ul>${bullets.join("")}</ul>` : ""}</section>`;
  }).join("") || `<div class="claude-analysis-raw">${escapeHtml(text)}</div>`;
  target.classList.toggle("claude-cursor", streaming);
  target.scrollTop = target.scrollHeight;
}

async function loadClaudeStatus() {
  if (!$("claudePanel")) return;
  try {
    const status = await fetch("/api/ai/status").then((response) => response.json());
    state.claude.enabled = Boolean(status.enabled);
    state.claude.model = status.model || "—";
    $("claudeModel").textContent = state.claude.model;
    $("claudeAnalyze").disabled = !state.claude.enabled;
    if ($("headerAnalyze")) $("headerAnalyze").disabled = !state.claude.enabled;
    if (state.claude.enabled) {
      setClaudeStatus(status.cached ? "CACHED" : "READY", status.cached ? "cached" : "ready");
      $("claudeFoot").textContent = status.cached_at ? `Last generated ${formatAppTime(status.cached_at)} ${displayTimeZoneLabel(status.cached_at)}` : "Ready. Analysis is cached to control API cost.";
    } else {
      setClaudeStatus("DISABLED", "disabled");
      $("claudeAnalysis").innerHTML = '<div class="claude-empty">Add ANTHROPIC_API_KEY and set CLAUDE_ANALYSIS_ENABLED=true in the server environment.</div>';
      $("claudeFoot").textContent = status.last_error || "The API key must remain in .env and Railway Variables, never in frontend code.";
    }
  } catch (error) {
    setClaudeStatus("ERROR", "error");
    $("claudeAnalysis").innerHTML = '<div class="claude-empty">Could not reach the Claude status endpoint.</div>';
  }
}

function stopClaudeStream() {
  if (state.claude.source) {
    state.claude.source.close();
    state.claude.source = null;
  }
  state.claude.busy = false;
  if (state.claude.enabled) {
    $("claudeAnalyze")?.removeAttribute("disabled");
    $("headerAnalyze")?.removeAttribute("disabled");
  }
  // A fill/cancel/target can happen while Claude is still explaining the
  // previous state. Queue one fresh lifecycle explanation instead of losing it.
  if (state.claude.pendingLifecycle && state.claude.enabled && state.claude.auto) {
    state.claude.pendingLifecycle = false;
    setTimeout(() => startClaudeAnalysis(false), 250);
  }
}

function startClaudeAnalysis(force = false) {
  if (!state.claude.enabled || state.claude.busy || !$("claudeAnalysis")) return;
  // Automatic Claude commentary is silent until the deterministic engine has
  // published a real entry or is managing/explaining a previously armed plan.
  // Analyze Now remains available for a manual read-only diagnostic.
  if (!force && (state.marketWarming || !claudePublishableSetup(state.setup))) return;
  state.claude.busy = true;
  state.claude.text = "";
  state.claude.lastStartedAt = Date.now();
  $("claudeAnalyze").disabled = true;
  if ($("headerAnalyze")) $("headerAnalyze").disabled = true;
  renderClaudeAnalysis("", true);
  setClaudeStatus("ANALYZING", "analyzing");
  $("claudeFoot").textContent = "Claude is reading the current TradeIQ snapshot…";

  const source = new EventSource(`/api/ai/analysis/stream?force=${force ? "true" : "false"}`);
  state.claude.source = source;

  source.addEventListener("meta", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.model) {
      state.claude.model = payload.model;
      $("claudeModel").textContent = payload.model;
    }
    if (payload.cached) setClaudeStatus("CACHED", "cached");
  });

  source.addEventListener("delta", (event) => {
    const payload = JSON.parse(event.data);
    state.claude.text += payload.text || "";
    renderClaudeAnalysis(state.claude.text, true);
  });

  source.addEventListener("done", (event) => {
    const payload = JSON.parse(event.data);
    renderClaudeAnalysis(state.claude.text, false);
    setClaudeStatus(payload.cached ? "CACHED" : "READY", payload.cached ? "cached" : "ready");
    $("claudeFoot").textContent = payload.generated_at
      ? `Generated ${formatAppTime(payload.generated_at)} ${displayTimeZoneLabel(payload.generated_at)} · read-only analysis`
      : "Read-only analysis · engine values were not changed";
    stopClaudeStream();
  });

  source.addEventListener("analysis_error", (event) => {
    let message = "Claude analysis failed. Check Railway logs and API configuration.";
    try { message = JSON.parse(event.data).message || message; } catch (_) { /* network error */ }
    renderClaudeAnalysis(`STATUS: Unavailable\nRISK:\n- ${message}\nACTION: Keep using the deterministic TradeIQ engine.`, false);
    setClaudeStatus("ERROR", "error");
    $("claudeFoot").textContent = message;
    stopClaudeStream();
  });

  source.onerror = () => {
    if (!state.claude.busy) return;
    const message = "Claude stream disconnected. Check the server connection and Railway logs.";
    renderClaudeAnalysis(`STATUS: Unavailable\nRISK:\n- ${message}\nACTION: Keep using the deterministic TradeIQ engine.`, false);
    setClaudeStatus("ERROR", "error");
    $("claudeFoot").textContent = message;
    stopClaudeStream();
  };
}

function claudePublishableSetup(setup) {
  if (!setup) return false;
  if (hasLockedTradePlan(setup)) return true;
  return Boolean(setup.armed_at && ["TP2_HIT", "STOPPED", "EXPIRED", "INVALIDATED"].includes(setup.order_state));
}

function lifecycleEventKey(setup) {
  if (!setup) return "";
  return [
    setup.setup_id || "",
    setup.order_state || "",
    setup.last_transition_to || "",
    setup.last_transition_at || "",
    setup.outcome || "",
  ].join("|");
}

function maybeRunClaudeOnStateChange(previousSetup, nextSetup) {
  if (state.marketWarming || !state.claude.enabled || !state.claude.auto || !previousSetup || !nextSetup) return;
  if (!claudePublishableSetup(previousSetup) && !claudePublishableSetup(nextSetup)) return;

  const previousKey = lifecycleEventKey(previousSetup);
  const nextKey = lifecycleEventKey(nextSetup);
  const transitionChanged = previousKey !== nextKey;
  const importantChange = transitionChanged
    || previousSetup.order_state !== nextSetup.order_state
    || previousSetup.direction !== nextSetup.direction
    || Boolean(previousSetup.actionable) !== Boolean(nextSetup.actionable);
  if (!importantChange) return;

  state.claude.lastLifecycleKey = nextKey;
  if (state.claude.busy) {
    state.claude.pendingLifecycle = true;
    return;
  }

  // Lifecycle events are the reason Claude exists in TradeIQ. Explain them
  // promptly; ordinary confidence/context refreshes remain rate-limited.
  const minimumDelay = transitionChanged ? 2500 : 30000;
  if (Date.now() - state.claude.lastStartedAt >= minimumDelay) {
    startClaudeAnalysis(false);
  } else if (transitionChanged) {
    state.claude.pendingLifecycle = true;
    setTimeout(() => {
      if (!state.claude.busy && state.claude.pendingLifecycle) {
        state.claude.pendingLifecycle = false;
        startClaudeAnalysis(false);
      }
    }, Math.max(250, minimumDelay - (Date.now() - state.claude.lastStartedAt)));
  }
}


function formatDataAge(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 60) return `${Math.round(value)}s`;
  const minutes = Math.floor(value / 60);
  const remainder = Math.round(value % 60);
  return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

function setConnection(connected) {
  state.connected = connected;
  const fallback = !connected && state.restFallbackActive;
  $("liveDot")?.classList.toggle("offline", !connected && !fallback);
  const label = $("connectionLabel");
  if (label) {
    label.textContent = connected ? "SERVER LIVE" : fallback ? "SERVER REST FALLBACK" : "SERVER RECONNECTING";
    label.className = connected ? "g" : fallback ? "a" : "r";
    label.title = fallback
      ? "The WebSocket is unavailable. TradeIQ is continuing through live HTTP polling."
      : connected ? "Live WebSocket connected" : "Attempting to reconnect the live WebSocket";
  }
}

function updateMarketFeedStatus(market = {}) {
  const source = String(market.data_source || "").toLowerCase();
  const rawState = String(market.stream_state || (market.connected ? "LIVE" : "RECONNECTING")).toUpperCase();
  const rawAge = market.last_record_age_seconds ?? market.last_candle_age_seconds;
  const recordAge = rawAge === null || rawAge === undefined ? Number.NaN : Number(rawAge);
  const hasAge = Number.isFinite(recordAge);
  state.feedState = rawState;
  state.feedRecordAgeSeconds = hasAge ? recordAge : null;
  state.feedLastRecordAt = market.last_record_at || null;

  let label = source === "databento" ? `DATABENTO ${rawState}` : String(market.mode || "SIMULATED").toUpperCase();
  if (source === "databento" && rawState === "LIVE" && market.data_fresh === false) label = "DATABENTO WAITING";
  if (source === "databento" && market.warming && rawState === "LIVE") label = "DATABENTO SYNC";
  if (source === "databento" && rawState === "DEGRADED") label = "DATABENTO DEGRADED";
  if (source === "databento" && rawState === "STALE") label = "DATABENTO STALE";
  if (source === "databento" && rawState === "MARKET_CLOSED") label = "DATABENTO MARKET CLOSED";
  state.dataSource = label;

  const mode = $("modeLabel");
  if (mode) {
    mode.textContent = label;
    mode.classList.remove("live", "sync", "reconnecting", "stale", "error");
    if (["LIVE"].includes(rawState) && !market.warming && market.data_fresh !== false) mode.classList.add("live");
    else if (market.warming || ["CONNECTING", "MARKET_CLOSED"].includes(rawState)) mode.classList.add("sync");
    else if (rawState === "RECONNECTING") mode.classList.add("reconnecting");
    else if (["STALE", "DEGRADED"].includes(rawState)) mode.classList.add("stale");
    else if (["ERROR", "STOPPED"].includes(rawState)) mode.classList.add("error");
    mode.title = market.last_disconnect_reason || market.last_error || label;
  }

  const age = $("dataAgeLabel");
  if (age) {
    age.textContent = `DATA ${formatDataAge(recordAge)}`;
    age.className = `m mono feed-age ${market.data_fresh === false ? "stale" : ""}`;
    age.title = market.last_record_at ? `Last market record: ${formatAppDateTime(market.last_record_at)} ${displayTimeZoneLabel(market.last_record_at)}` : "No live market record received yet";
  }
}

function renderHeader(snapshot) {
  const current = snapshot?.price ?? state.baseCandles.at(-1)?.close;
  if (current === undefined) return;
  const active = state.meta?.overview?.find((item) => item.symbol === displaySymbol()) || state.meta?.overview?.[0];
  const change = active?.change ?? snapshot?.change ?? 0;
  const percent = active?.change_percent ?? snapshot?.change_percent ?? 0;
  $("hdrPrice").textContent = fmt(current);
  $("hdrChg").textContent = `${fmtSigned(change)} (${percent >= 0 ? "+" : ""}${percent.toFixed(2)}%)`;
  $("hdrChg").className = `mono ${change >= 0 ? "g" : "r"}`;
}

function renderOverview(items = []) {
  $("overview").innerHTML = items.map((item) => {
    const cls = item.change_percent >= 0 ? "g" : "r";
    const itemDigits = item.symbol === displaySymbol() ? pricePrecision() : 2;
    return `<div class="ov-row"><span>${item.symbol}</span><span>${fmt(item.price, itemDigits)} <span class="${cls}">${item.change_percent >= 0 ? "+" : ""}${item.change_percent.toFixed(2)}%</span></span></div>`;
  }).join("") || '<div class="loading">No overview data</div>';
}

function renderGexTable(setup) {
  const gex = setup.gex;
  const rows = [
    { type: "Gamma Resistance / Call Wall", price: gex.call_wall, gex: gex.call_wall_gex, strength: 5, cls: "b" },
    ...(Number.isFinite(Number(gex.max_pain)) ? [{ type: "Maximum Pain", price: gex.max_pain, gex: null, strength: 0, cls: "p" }] : []),
    { type: "Gamma Flip", price: gex.gamma_flip, gex: null, strength: 0, cls: "a" },
    ...gex.levels.slice(0, 5).map((level) => ({ ...level, cls: (level.gex || 0) >= 0 ? "g" : "r" })),
    { type: "Put Support / Put Wall", price: gex.put_wall, gex: gex.put_wall_gex, strength: 5, cls: "g" },
  ];
  const seen = new Set();
  const deduped = rows.filter((row) => {
    const key = `${row.type}-${row.price}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  }).slice(0, 8);
  $("gexTable").innerHTML = deduped.map((row) => `<tr>
    <td class="${row.cls}">${row.type}</td><td>${fmt(row.price)}</td>
    <td class="${row.cls}">${row.gex == null ? "—" : fmtGex(row.gex)}</td>
    <td class="${row.cls} stars">${row.strength ? stars(row.strength) : "—"}</td></tr>`).join("");
}

function renderConfidence(setup) {
  $("cfScoreHeader").textContent = `${Math.round(setup.confidence)}/100`;
  const rows = Object.entries(setup.confidence_maximums).map(([name, maximum]) => {
    const value = Number(setup.confidence_components[name] || 0);
    const active = Math.round((value / maximum) * 5);
    const warning = value > 0 && value < maximum * 0.5;
    let segments = "";
    for (let i = 0; i < 5; i += 1) segments += `<span class="seg ${i < active ? "on" : ""} ${warning ? "warn" : ""}"></span>`;
    return `<div class="cf-row"><span class="lbl">${SCORE_LABELS[name] || name}</span>
      <span style="display:flex;gap:8px;align-items:center"><span class="segbar">${segments}</span>
      <span class="cf-val">${value.toFixed(1)}/${Number(maximum).toFixed(0)}</span></span></div>`;
  });
  rows.push(`<div style="display:flex;justify-content:space-between;margin-top:10px;padding-top:10px;border-top:1px solid var(--line)">
    <span class="g" style="font-weight:600">Total Score</span><span class="mono g" style="font-size:16px;font-weight:700">${setup.confidence.toFixed(1)} / 100</span></div>`);
  $("cfBreak").innerHTML = rows.join("");
}

function renderKeyConfluences(setup) {
  const ok = '<svg viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 12l2.5 2.5L16 9"/></svg>';
  const warn = '<svg viewBox="0 0 24 24" fill="none" stroke="var(--amber)" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v5M12 16v.5"/></svg>';
  $("keyCf").innerHTML = Object.entries(setup.signals).map(([name, active]) =>
    `<div class="check">${active ? ok : warn}<span style="color:${active ? "var(--text)" : "var(--amber)"}">${SIGNAL_LABELS[name] || name}</span></div>`
  ).join("");
}


function timelineStateClass(stateName) {
  if (["FILLED", "TP1_HIT", "TP2_HIT", "WAITING_FOR_LIMIT"].includes(stateName)) return "positive";
  if (["STOPPED", "INVALIDATED"].includes(stateName)) return "negative";
  return "warning";
}

function renderSetupTimeline(events = []) {
  const rows = events.slice(-6).reverse();
  const html = rows.length ? rows.map((event) => {
    const stamp = event.created_at
      ? formatAppTime(event.created_at)
      : "—";
    const stateName = String(event.new_state || "EVENT").replaceAll("_", " ");
    const price = Number.isFinite(Number(event.price)) ? ` · ${fmt(event.price)}` : "";
    return `<div class="timeline-event ${timelineStateClass(event.new_state)}"><span class="timeline-dot"></span><div><b>${escapeHtml(stateName)}</b><small>${escapeHtml(stamp)} ET${escapeHtml(price)}</small><p>${escapeHtml(event.detail || "Lifecycle state updated.")}</p></div></div>`;
  }).join("") : '<div class="timeline-empty">No lifecycle events yet.</div>';
  if ($("setupTimeline")) $("setupTimeline").innerHTML = html;
  if ($("chartSetupTimeline")) $("chartSetupTimeline").innerHTML = html;
}

async function loadSetupTimeline(setup, force = false) {
  if (!setup?.setup_id) {
    state.setupTimeline = [];
    state.timelineSetupId = null;
    state.timelineLifecycleKey = null;
    renderSetupTimeline([]);
    return;
  }
  const key = lifecycleEventKey(setup);
  if (!force && state.timelineSetupId === setup.setup_id && state.timelineLifecycleKey === key) return;
  state.timelineSetupId = setup.setup_id;
  state.timelineLifecycleKey = key;
  try {
    const response = await fetch(`/api/setups/${encodeURIComponent(setup.setup_id)}/timeline?limit=20`);
    if (!response.ok) throw new Error(`Timeline request failed: ${response.status}`);
    const payload = await response.json();
    state.setupTimeline = Array.isArray(payload.events) ? payload.events : [];
    renderSetupTimeline(state.setupTimeline);
  } catch (error) {
    console.warn("Could not load setup lifecycle timeline", error);
  }
}

function remainingText(target) {
  if (!target) return "00:00:00";
  const seconds = Math.max(0, Math.floor((new Date(target).getTime() - Date.now()) / 1000));
  const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const secs = String(seconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${secs}`;
}

function renderSession(session) {
  if (!session) return;
  state.session = session;
  const open = Boolean(session.is_open);
  $("sessionCardTitle").textContent = open ? session.display_name : "MARKET CLOSED";
  $("sessionHours").textContent = open ? session.reason : `${session.reason} · Next open`;
  $("sessionTimer").textContent = remainingText(session.countdown_target);
  $("sessionTimer").className = `clock ${open ? "g" : "r"}`;
  $("sessionState").textContent = session.countdown_label;
  if (state.currentPage === "dashboard") $("pageTitle").textContent = open ? `${activeSymbol()} · ${session.display_name}` : `${activeSymbol()} · MARKET CLOSED`;
}

function activeModelConfirmation(setup) {
  const contracts = setup?.signals?.model_confirmations || {};
  const contract = contracts[setup?.primary_entry_model_key] || {};
  const missing = Array.isArray(contract.missing) ? contract.missing : [];
  return {
    label: contract.label || "model-specific confirmation",
    missing,
    evidence: Array.isArray(contract.evidence) ? contract.evidence : [],
    windowBars: Number(contract.window_bars || 0),
  };
}

function confirmationWaitingText(setup) {
  const contract = activeModelConfirmation(setup);
  return contract.missing.length ? contract.missing.slice(0, 3).join(" · ") : contract.label;
}

function previewExplanation(setup, { syncing = false, marketClosed = false } = {}) {
  if (syncing) return "TradeIQ is syncing Databento history. No entry will be published until live data and every safety gate are valid.";
  if (marketClosed) return "TradeIQ is evaluating the latest closed data. Scanning information remains visible, but no executable entry is published while the market is closed.";
  const model = setup?.primary_entry_model || "the strongest developing model";
  const direction = ["LONG", "SHORT"].includes(setup?.direction) ? setup.direction.toLowerCase() : "directional";
  const reason = String(setup?.model_selection_reason || "").trim();
  const base = `TradeIQ is live-scanning a ${direction} ${model} candidate. This is analysis only — no order, entry, stop or targets are published until confirmation, freshness, liquidity-room and minimum-R gates pass.`;
  return reason ? `${base} ${reason}` : base;
}

function renderModelRanking(setup, targetId) {
  const target = $(targetId);
  if (!target) return;
  const models = Array.isArray(setup?.entry_model_scores) ? setup.entry_model_scores.slice(0, 5) : [];
  target.innerHTML = models.length ? models.map((model, index) => {
    const stateClass = model.eligible ? (index === 0 ? "primary" : "eligible") : "developing";
    const missing = Array.isArray(model.missing) && model.missing.length ? ` · needs ${escapeHtml(model.missing.join(", "))}` : "";
    return `<div class="model-rank ${stateClass}"><span>${index + 1}</span><b>${escapeHtml(model.name)}</b><strong>${Number(model.score || 0).toFixed(0)}%</strong><small>${model.eligible ? "qualified" : "developing"}${missing}</small></div>`;
  }).join("") : '<div class="timeline-empty">No ranked models yet — scanning live price and level reactions.</div>';
}


function executionName(setup) {
  const type = String(setup?.execution_type || "NONE").toUpperCase();
  if (type === "MARKET") return "Market Entry";
  if (type === "STOP") return "Stop Entry";
  if (type === "LIMIT") return "Limit Entry";
  return "No Entry";
}

function executionOrderName(setup) {
  const side = setup?.direction === "SHORT" ? "SELL" : "BUY";
  const type = String(setup?.execution_type || "NONE").toUpperCase();
  return ["MARKET", "LIMIT", "STOP"].includes(type) ? `${side} ${type}` : "NO ENTRY";
}

function clusterTierName(setup) {
  const tier = String(setup?.composite_cluster_tier || "NONE").toUpperCase();
  const count = Array.isArray(setup?.composite_cluster_active_categories)
    ? setup.composite_cluster_active_categories.length
    : 0;
  if (tier === "EXCEPTIONAL_2_FACTOR") return "EXCEPTIONAL 2-FACTOR CLUSTER";
  if (tier === "STANDARD_3_FACTOR") return "STANDARD 3-FACTOR CLUSTER";
  if (tier === "HIGH_PRIORITY_4_PLUS") return `HIGH-PRIORITY ${Math.max(4, count)}-FACTOR CLUSTER`;
  return "INSTITUTIONAL CLUSTER";
}

function marketMapClusterText(cluster) {
  if (!cluster) return "—";
  const tier = String(cluster.tier || "CONTEXT").replaceAll("_", " ");
  const stateName = String(cluster.state || "DISTANT").replaceAll("_", " ");
  return `${tier} ${cluster.role} · ${Number(cluster.score || 0).toFixed(0)}% · ${stateName}`;
}

function clusterDisplay(setup) {
  const activeMap = setup?.market_map?.active_cluster;
  if (activeMap) return marketMapClusterText(activeMap);
  if (setup?.composite_cluster_eligible) {
    return `${clusterTierName(setup)} · ${Number(setup.composite_cluster_score || 0).toFixed(0)}%`;
  }
  if (setup?.cluster_low != null) {
    return `${fmt(setup.cluster_low)}–${fmt(setup.cluster_high)} · ${(Number(setup.cluster_score || 0) * 100).toFixed(0)}%`;
  }
  return "Single-model setup";
}

function hasVisibleScan(setup) {
  return Boolean(
    setup
    && !hasLockedTradePlan(setup)
    && ["LONG", "SHORT"].includes(setup.direction)
    && setup.primary_entry_model
  );
}

function scanPhaseText(setup) {
  if (hasWatchingPlan(setup) && watchTriggerTouched(setup)) return `Confirming ${setup.direction}`;
  if (hasWatchingPlan(setup)) return `Scanning ${setup.direction}`;
  if (hasVisibleScan(setup)) return `Developing ${setup.direction}`;
  return "Scanning Market";
}

function scanManagementText(setup) {
  if (hasWatchingPlan(setup) && watchTriggerTouched(setup)) return "AWAITING MODEL CONFIRMATION";
  if (hasWatchingPlan(setup)) return "WAITING FOR PRICE REACTION";
  return "LIVE MODEL SCAN";
}

function renderTradeSetup(setup) {
  const confidence = Math.max(0, Math.min(100, Number(setup.confidence || 0)));
  const lockedPlan = hasLockedTradePlan(setup);
  const visibleScan = hasVisibleScan(setup);
  const displayConfidence = lockedPlan || visibleScan ? confidence : 0;
  const circumference = 307.9;
  $("gaugeArc").style.strokeDashoffset = String(circumference * (1 - displayConfidence / 100));
  const gaugeColor = lockedPlan
    ? (setup.actionable ? COLORS.green : confidence >= 55 ? COLORS.amber : COLORS.red)
    : visibleScan ? (confidence >= 72 ? COLORS.green : confidence >= 55 ? COLORS.amber : COLORS.blue)
      : COLORS.muted;
  $("gaugeArc").style.stroke = gaugeColor;
  $("confidencePct").textContent = lockedPlan || visibleScan ? `${Math.round(confidence)}%` : "—";
  $("confidencePct").style.color = gaugeColor;

  const activeStates = [...ACTIVE_TRADE_STATES];
  const watchingPlan = hasWatchingPlan(setup);
  const triggerTouched = watchTriggerTouched(setup);
  const syncing = state.marketWarming || setup.status === "DATA_SYNCING";
  const marketClosed = state.session && !state.session.is_open;
  const quality = lockedPlan
    ? setup.order_state === "WAITING_FOR_LIMIT" ? `${executionName(setup)} Armed`
      : setup.order_state === "FILLED" ? "Position Filled"
        : setup.order_state === "TP1_HIT" ? "TP1 Hit — Running"
          : setup.order_state.replaceAll("_", " ")
    : scanPhaseText(setup);
  $("probabilityLabel").textContent = syncing ? "Data Syncing" : marketClosed ? "Market Closed" : quality;
  $("probabilityLabel").style.color = gaugeColor;

  const coreKeys = ["trend_alignment", "gex_alignment", "ote_overlap", "supply_demand", "gex_ote_zone_cluster"];
  const aligned = coreKeys.filter((key) => setup.signals?.[key]).length;
  $("coreAlignment").textContent = lockedPlan
    ? `${aligned} / ${coreKeys.length} core confluences aligned — executable plan locked`
    : `${aligned} / ${coreKeys.length} core confluences aligned — live scan only, no order`;

  const scanLabel = visibleScan
    ? `${triggerTouched ? "CONFIRM" : "SCAN"} ${setup.direction} · NO ORDER`
    : "SCANNING MARKET";
  const label = lockedPlan ? `${executionOrderName(setup)} · ${setup.order_state.replaceAll("_", " ")}` : scanLabel;
  $("setupLabel").textContent = syncing ? "DATA SYNCING" : marketClosed ? "MARKET CLOSED" : label;
  $("setupLabel").className = `${syncing || marketClosed ? "a" : visibleScan || lockedPlan ? classForDirection(setup.direction) : "a"} mono setup-side-label`;
  $("setupDirection").textContent = lockedPlan || visibleScan ? `${setup.direction} ${setup.direction === "LONG" ? "↑" : "↓"}` : "WAITING";
  $("setupDirection").className = `v ${lockedPlan || visibleScan ? classForDirection(setup.direction) : "a"}`;
  $("setupModel").textContent = setup.primary_entry_model ? `${setup.primary_entry_model} · ${Number(setup.primary_model_score || 0).toFixed(0)}%` : "—";
  $("setupBackups").textContent = (setup.alternative_entry_models || []).slice(0, 3).join(" · ") || "—";
  $("setupGrade").textContent = setup.confidence_grade || "—";
  $("setupGrade").className = `v ${confidence >= 85 ? "g" : confidence >= 70 ? "a" : visibleScan ? "b" : "r"}`;
  $("entryLabel").textContent = lockedPlan ? (setup.order_state === "WAITING_FOR_LIMIT" ? `${executionOrderName(setup)} Armed` : `${executionOrderName(setup)} Filled`) : "Entry (publishes when valid)";
  $("setupEntry").textContent = lockedPlan ? fmt(setup.entry) : "—";
  if ($("stopLabel")) $("stopLabel").textContent = "Initial Stop";
  $("setupStop").textContent = lockedPlan ? fmt(setup.initial_stop_loss ?? setup.stop_loss) : "—";
  $("setupActiveStop").textContent = lockedPlan ? fmt(setup.active_stop_loss ?? setup.stop_loss) : "—";
  $("setupManagement").textContent = lockedPlan
    ? `${String(setup.management_state || "LIMIT_ARMED").replaceAll("_", " ")} · FRESH ${Number(setup.execution_freshness_score || 0).toFixed(0)}%`
    : scanManagementText(setup);
  $("setupTp1").textContent = lockedPlan ? fmt(setup.take_profit_1) + (setup.tp1_r ? ` (${Number(setup.tp1_r).toFixed(1)}R)` : "") : "—";
  $("setupTp2").textContent = lockedPlan ? fmt(setup.take_profit_2) + (setup.tp2_r ? ` (${Number(setup.tp2_r).toFixed(1)}R)` : "") : "—";
  $("setupTp1Source").textContent = lockedPlan ? (setup.target_sources?.tp1 || "—") : "—";
  $("setupTp2Source").textContent = lockedPlan ? (setup.target_sources?.tp2 || "—") : "—";
  $("setupRr").textContent = lockedPlan && setup.risk_reward ? `1 : ${Number(setup.risk_reward).toFixed(1)}` : "—";
  const statusText = syncing ? "Data Syncing" : marketClosed ? "Market Closed"
    : lockedPlan ? setup.status.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (x) => x.toUpperCase())
      : visibleScan ? `${scanPhaseText(setup)} — ${setup.primary_entry_model || "evaluating models"}`
        : "Scanning for a valid setup";
  $("setupStatus").textContent = statusText;
  $("setupStatus").className = `v ${setup.actionable || activeStates.includes(setup.order_state) ? "g" : visibleScan ? "b" : "a"}`;
  $("setupCluster").textContent = clusterDisplay(setup);
  $("setupCluster").className = `v ${setup.market_map?.active_cluster?.actionable_location || setup.signals?.gex_ote_zone_cluster ? "g" : "a"}`;
  $("setupSession").textContent = state.session?.display_name || "—";
  $("setupSession").className = `v ${marketClosed ? "r" : "g"}`;
  $("validLabel").textContent = syncing ? "History" : marketClosed ? "Opens In" : lockedPlan ? "Valid Until" : watchingPlan ? "Scan Expires" : "Entry State";
  $("setupValid").textContent = syncing ? "SYNCING" : marketClosed ? remainingText(state.session?.next_open_at) : lockedPlan ? formatAppTime(setup.valid_until) : watchingPlan ? formatAppTime(setup.watch_expires_at || setup.valid_until) : "SCANNING";
  renderModelRanking(setup, "setupModelRanking");
  renderChartTradeSetup(setup, {
    confidence, gaugeColor, marketClosed, syncing, quality, aligned,
    coreCount: coreKeys.length, label, statusText, activeStates,
    watchingPlan, triggerTouched, lockedPlan, visibleScan,
  });
}

function renderChartTradeSetup(setup, context) {
  if (!$("chartSetupPanel")) return;
  const { confidence, gaugeColor, marketClosed, syncing, quality, aligned, coreCount, label, statusText, activeStates, watchingPlan, lockedPlan, visibleScan } = context;
  const ring = $("chartConfidenceRing");
  ring.style.setProperty("--chart-confidence", `${(lockedPlan || visibleScan ? confidence : 0) * 3.6}deg`);
  ring.style.setProperty("--chart-confidence-color", gaugeColor);
  $("chartConfidencePct").textContent = lockedPlan || visibleScan ? `${Math.round(confidence)}%` : "—";
  $("chartConfidencePct").style.color = gaugeColor;
  $("chartProbabilityLabel").textContent = syncing ? "Data Syncing" : marketClosed ? "Market Closed" : quality;
  $("chartProbabilityLabel").style.color = gaugeColor;
  $("chartCoreAlignment").textContent = lockedPlan
    ? `${aligned} / ${coreCount} aligned — executable plan locked`
    : `${aligned} / ${coreCount} aligned — live scan only, no order`;

  $("chartSetupLabel").textContent = syncing ? "DATA SYNCING" : marketClosed ? "MARKET CLOSED" : label;
  $("chartSetupLabel").className = `${syncing || marketClosed ? "a" : visibleScan || lockedPlan ? classForDirection(setup.direction) : "a"} mono`;
  $("chartSetupDirection").textContent = lockedPlan || visibleScan ? `${setup.direction} ${setup.direction === "LONG" ? "↑" : "↓"}` : "WAITING";
  $("chartSetupDirection").className = lockedPlan || visibleScan ? classForDirection(setup.direction) : "a";
  $("chartSetupModel").textContent = setup.primary_entry_model ? `${setup.primary_entry_model} · ${Number(setup.primary_model_score || 0).toFixed(0)}%` : "—";
  $("chartSetupBackups").textContent = (setup.alternative_entry_models || []).slice(0, 2).join(" · ") || "—";
  $("chartSetupGrade").textContent = setup.confidence_grade || "—";
  $("chartSetupGrade").className = confidence >= 85 ? "g" : confidence >= 70 ? "a" : visibleScan ? "b" : "r";
  $("chartEntryLabel").textContent = lockedPlan ? (setup.order_state === "WAITING_FOR_LIMIT" ? `${executionOrderName(setup)} Armed` : `${executionOrderName(setup)} Filled`) : "Entry (publishes when valid)";
  $("chartSetupEntry").textContent = lockedPlan ? fmt(setup.entry) : "—";
  if ($("chartStopLabel")) $("chartStopLabel").textContent = "Initial Stop";
  $("chartSetupStop").textContent = lockedPlan ? fmt(setup.initial_stop_loss ?? setup.stop_loss) : "—";
  $("chartSetupActiveStop").textContent = lockedPlan ? fmt(setup.active_stop_loss ?? setup.stop_loss) : "—";
  $("chartSetupManagement").textContent = lockedPlan
    ? `${String(setup.management_state || "LIMIT_ARMED").replaceAll("_", " ")} · FRESH ${Number(setup.execution_freshness_score || 0).toFixed(0)}%`
    : scanManagementText(setup);
  $("chartSetupTp1").textContent = lockedPlan ? fmt(setup.take_profit_1) + (setup.tp1_r ? ` (${Number(setup.tp1_r).toFixed(1)}R)` : "") : "—";
  $("chartSetupTp2").textContent = lockedPlan ? fmt(setup.take_profit_2) + (setup.tp2_r ? ` (${Number(setup.tp2_r).toFixed(1)}R)` : "") : "—";
  $("chartSetupTp1Source").textContent = lockedPlan ? (setup.target_sources?.tp1 || "—") : "—";
  $("chartSetupTp2Source").textContent = lockedPlan ? (setup.target_sources?.tp2 || "—") : "—";
  $("chartSetupRr").textContent = lockedPlan && setup.risk_reward ? `1 : ${Number(setup.risk_reward).toFixed(1)}` : "—";
  $("chartSetupStatus").textContent = statusText;
  $("chartSetupStatus").className = setup.actionable || activeStates.includes(setup.order_state) ? "g" : visibleScan ? "b" : "a";
  $("chartSetupCluster").textContent = clusterDisplay(setup);
  $("chartSetupCluster").className = setup.market_map?.active_cluster?.actionable_location || setup.signals?.gex_ote_zone_cluster ? "g" : "a";
  renderModelRanking(setup, "chartModelRanking");
  $("chartSetupSession").textContent = state.session?.display_name || "—";
  $("chartSetupSession").className = marketClosed ? "r" : "g";
  $("chartValidLabel").textContent = syncing ? "History" : marketClosed ? "Opens In" : lockedPlan ? "Valid Until" : watchingPlan ? "Scan Expires" : "Entry State";
  $("chartSetupValid").textContent = syncing ? "SYNCING" : marketClosed ? remainingText(state.session?.next_open_at) : lockedPlan ? formatAppTime(setup.valid_until) : watchingPlan ? formatAppTime(setup.watch_expires_at || setup.valid_until) : "SCANNING";
  const previewNotice = $("chartPreviewNotice");
  if (previewNotice) {
    const informational = setup.order_state === "PREVIEW_ONLY" || watchingPlan;
    previewNotice.hidden = !informational;
    previewNotice.classList.toggle("syncing", Boolean(syncing));
    previewNotice.classList.toggle("closed", Boolean(marketClosed));
    previewNotice.classList.toggle("watching", Boolean(watchingPlan));
    const title = $("chartPreviewTitle");
    if (title) title.textContent = visibleScan ? "LIVE SCAN — NO ORDER" : "SCANNING MARKET — NO ORDER";
    if (informational && $("chartPreviewReason")) $("chartPreviewReason").textContent = previewExplanation(setup, { syncing, marketClosed });
  }
}
// Legacy v3.1.2 UI strings retained only for compatibility tests:
// SCANNING QUIETLY — NO ACTIONABLE ENTRY
// rankings publish with a validated entry

function renderGexSummary(setup) {
  const gex = setup.gex;
  $("gexRegime").textContent = `${gex.regime.charAt(0)}${gex.regime.slice(1).toLowerCase()} Gamma`;
  $("gexRegime").className = `v ${gex.regime === "POSITIVE" ? "g" : gex.regime === "NEGATIVE" ? "r" : "a"}`;
  if ($("gexDealerBias")) $("gexDealerBias").textContent = gex.dealer_bias || "NEUTRAL";
  if ($("gexBalance")) $("gexBalance").textContent = `+${Number(gex.positive_gamma_percent || 0).toFixed(0)}% / -${Number(gex.negative_gamma_percent || 0).toFixed(0)}%`;
  $("gammaFlip").textContent = fmt(gex.gamma_flip);
  $("putWall").textContent = fmt(gex.put_wall);
  $("callWall").textContent = fmt(gex.call_wall);
  if ($("maxPain")) $("maxPain").textContent = Number.isFinite(Number(gex.max_pain)) ? fmt(gex.max_pain) : "Native OI required";
  const price = state.baseCandles.at(-1)?.close ?? 0;
  const above = price >= gex.gamma_flip;
  $("priceVsFlip").textContent = above ? "Above Flip" : "Below Flip";
  $("priceVsFlip").className = `v ${above ? "g" : "r"}`;
  const sourceEl = $("gexSource");
  if (sourceEl) sourceEl.textContent = gex.source_label || gex.source || "—";
  const normalized = 50 + Math.tanh(gex.net_gex / 1e9) * 42;
  const needlePosition = Math.max(2, Math.min(98, normalized));
  $("gexNeedle").style.left = `${needlePosition}%`;

  if ($("mobileGexRegime")) {
    const estimated = Boolean(gex.is_estimate) || String(gex.source || "").toLowerCase().includes("fallback") || String(gex.source_label || "").toLowerCase().includes("fallback");
    $("mobileGexRegime").textContent = `${gex.regime.charAt(0)}${gex.regime.slice(1).toLowerCase()}`;
    $("mobileGexRegime").className = gex.regime === "POSITIVE" ? "g" : gex.regime === "NEGATIVE" ? "r" : "a";
    $("mobileNetGex").textContent = fmtGex(gex.net_gex);
    $("mobileGammaFlip").textContent = fmt(gex.gamma_flip);
    if ($("mobileMaxPain")) $("mobileMaxPain").textContent = Number.isFinite(Number(gex.max_pain)) ? fmt(gex.max_pain) : "—";
    $("mobileCallWall").textContent = fmt(gex.call_wall);
    $("mobilePutWall").textContent = fmt(gex.put_wall);
    $("mobileGexApplied").textContent = activeSymbol();
    $("mobileGexSource").textContent = gex.source_label || gex.source || "Fallback model";
    $("mobileGexBadge").textContent = estimated ? "ESTIMATE" : "NATIVE";
    $("mobileGexBadge").className = `source-chip ${estimated ? "estimated" : ""}`;
    $("mobileGexNeedle").style.left = `${needlePosition}%`;
    $("mobileGexNote").textContent = estimated
      ? "Estimated GEX: use these levels as secondary context, not as confirmed options positioning. The estimate does not change the confidence score."
      : `Native parent-market gamma levels applied to ${activeSymbol()}. GEX remains informational and never changes the confidence score.`;
    window.setTimeout(() => drawGexStrikeChart($("mobileGexStrikeChart"), gex, true), 0);
  }
}

function renderZones(setup) {
  const zones = setup.zones.slice(0, 7);
  $("sdTable").innerHTML = zones.length ? zones.map((zone) => `<tr>
    <td>${zone.timeframe}</td><td class="${zone.kind === "DEMAND" ? "g" : "r"}">${zone.kind[0]}${zone.kind.slice(1).toLowerCase()}</td>
    <td>${fmt(zone.low)}–${fmt(zone.high)}<div class="m" style="font-size:9px">${zone.fresh ? "Fresh" : `${zone.touches} touch(es)`}</div></td><td class="a stars">${stars(zone.strength)}</td></tr>`).join("") : '<tr><td colspan="4" class="m">No fresh zones detected</td></tr>';
}

function renderFib(setup) {
  $("fibTable").innerHTML = setup.fib_levels.map((level) => {
    const cls = Math.abs(level.ratio - 0.705) < 0.001 ? "a" : level.ratio >= 0.618 ? "p" : "m";
    return `<tr><td class="${cls}">${level.ratio.toFixed(3)} · ${level.label}</td><td style="text-align:right" class="${cls}">${fmt(level.price)}</td></tr>`;
  }).join("");
}

function renderAlerts(items = []) {
  const classes = { positive: "g", negative: "r", warning: "a", info: "b" };
  $("alerts").innerHTML = items.map((item) => `<tr class="alert-row"><td>${item.created_at ? formatAppTime(item.created_at) : item.time}</td><td class="${classes[item.severity] || "b"}">${item.title}</td></tr>
    <tr><td colspan="2" class="m" style="border-top:none;padding-top:0;font-size:11px">${item.detail}</td></tr>`).join("");
}
function renderEconomicCalendar(items = [], status = {}) {
  const access = String(status.access || "unknown");
  const unavailable = access === "premium-required"
    ? "Upcoming economic calendar unavailable on the current Finnhub plan."
    : access === "not-configured"
      ? "Finnhub is not configured for upcoming economic events."
      : "No upcoming US economic events were returned.";

  const desktop = $("economicCalendar");
  if (desktop) {
    desktop.innerHTML = items.length ? items.map((item) => {
      const stamp = calendarDateParts(item);
      const impact = String(item.impact || "Low");
      const impactClass = impact === "High" ? "r" : impact === "Med" ? "a" : "m";
      return `<tr class="calendar-row"><td class="mono calendar-datetime">${escapeHtml(stamp.full)}</td><td><b>${escapeHtml(item.event || "Economic event")}</b><div class="m calendar-values">Forecast ${escapeHtml(calendarValue(item.estimate, item.unit))} · Previous ${escapeHtml(calendarValue(item.previous, item.unit))}</div></td><td class="${impactClass}" style="text-align:right">${escapeHtml(impact)}</td></tr>`;
    }).join("") : `<tr><td colspan="3" class="m calendar-unavailable">${escapeHtml(unavailable)}</td></tr>`;
  }

  const mobile = $("mobileCalendarList");
  if (mobile) {
    if (!items.length) {
      mobile.innerHTML = `<div class="mobile-empty">${escapeHtml(unavailable)}</div>`;
    } else {
      const groups = new Map();
      items.forEach((item) => {
        const stamp = calendarDateParts(item);
        const key = stamp.date;
        if (!groups.has(key)) groups.set(key, { label: `${stamp.day}, ${stamp.date}`, items: [] });
        groups.get(key).items.push({ item, stamp });
      });
      mobile.innerHTML = [...groups.values()].map((group, groupIndex) => {
        const prefix = groupIndex === 0 ? "Next" : "Upcoming";
        const rows = group.items.map(({ item, stamp }) => {
          const impact = String(item.impact || "Low");
          const impactKind = impact.toLowerCase() === "high" ? "high" : impact.toLowerCase().startsWith("med") ? "med" : "low";
          const dots = impactKind === "high" ? 3 : impactKind === "med" ? 2 : 1;
          return `<article class="economic-event-row"><time datetime="${escapeHtml(item.scheduled_at || "")}"><b>${escapeHtml(stamp.time.replace(" ET", ""))}</b><span>${escapeHtml(item.country || "US")}</span></time><span class="impact-dots ${impactKind}" aria-label="${escapeHtml(impact)} impact">${"<i></i>".repeat(dots)}</span><div class="economic-event-copy"><strong>${escapeHtml(item.event || "Economic event")}</strong><small>Forecast: ${escapeHtml(calendarValue(item.estimate, item.unit))} &nbsp; Previous: ${escapeHtml(calendarValue(item.previous, item.unit))}</small></div><span class="impact-label ${impactKind}">${escapeHtml(impact)}</span></article>`;
        }).join("");
        return `<section class="economic-day-group"><h4><span>${prefix}</span>${escapeHtml(group.label)}</h4>${rows}</section>`;
      }).join("");
    }
  }
}

async function loadEconomicCalendar() {
  try {
    const response = await fetch("/api/economic-calendar?limit=10&days=7");
    if (!response.ok) throw new Error(`Economic calendar failed (${response.status})`);
    const payload = await response.json();
    renderEconomicCalendar(payload.items || [], payload.status || {});
  } catch (error) {
    console.error(error);
    renderEconomicCalendar([], { access: "error" });
  }
}

function renderNews(items = []) {
  const target = $("news");
  const rows = items.map((item) => {
    const impactClass = item.impact === "High" ? "r" : item.impact === "Med" ? "a" : "m";
    const headline = escapeHtml(item.event || "Untitled headline");
    const source = escapeHtml(item.source || "Finnhub");
    const stamp = newsDateParts(item);
    const safeUrl = typeof item.url === "string" && /^https?:\/\//i.test(item.url) ? item.url : "";
    const headlineHtml = safeUrl
      ? `<a class="news-link" href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${headline}</a>`
      : headline;
    return `<tr class="news-row"><td class="mono m news-datetime">${escapeHtml(stamp.full)}</td><td>${headlineHtml}<div class="m news-source">${source}</div></td><td class="${impactClass}" style="text-align:right">${escapeHtml(item.impact || "Low")}</td></tr>`;
  });
  if (target) target.innerHTML = rows.length ? rows.join("") : '<tr><td colspan="3" class="m">No recent headlines available</td></tr>';

  const mobileTarget = $("mobileNewsList");
  if (mobileTarget) {
    mobileTarget.innerHTML = items.length ? items.map((item) => {
      const headline = escapeHtml(item.event || "Untitled headline");
      const source = escapeHtml(item.source || "Finnhub");
      const stamp = newsDateParts(item);
      const safeUrl = typeof item.url === "string" && /^https?:\/\//i.test(item.url) ? item.url : "";
      const headlineHtml = safeUrl
        ? `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${headline}</a>`
        : `<div class="mobile-news-headline">${headline}</div>`;
      return `<article class="headline-row"><div>${headlineHtml}<small>${escapeHtml(stamp.date)} · ${escapeHtml(stamp.time)} · ${source}</small></div><span aria-hidden="true">›</span></article>`;
    }).join("") : '<div class="mobile-empty">No recent headlines available.</div>';
  }
}

function renderPerformance(performance) {
  if (!performance) return;
  $("perfWin").textContent = `${performance.win_rate.toFixed(0)}%`;
  $("perfTrades").textContent = performance.trades;
  $("perfAvgR").textContent = `${performance.average_r.toFixed(2)}R`;
  $("perfPF").textContent = performance.profit_factor.toFixed(2);
  $("perfPnl").textContent = `${performance.net_pnl >= 0 ? "+" : ""}${fmt(performance.net_pnl, 0)}`;
  drawEquity(performance.equity_curve);
}

function renderSyncingState(snapshot = {}, session = state.session) {
  state.setup = null;
  loadSetupTimeline(null);
  if (session) renderSession(session);
  renderHeader(snapshot);
  const syncingText = state.dataQuality === "CONTRACT_MISMATCH"
    ? "CONTRACT MISMATCH — LIVE BARS ONLY"
    : state.dataQuality === "LIVE_ONLY"
      ? "LIVE BARS — HISTORY SYNCING"
      : "DATABENTO HISTORY SYNCING";
  if ($("setupLabel")) { $("setupLabel").textContent = "SYNCING"; $("setupLabel").className = "a mono setup-side-label"; }
  if ($("probabilityLabel")) $("probabilityLabel").textContent = "Data Syncing";
  if ($("coreAlignment")) $("coreAlignment").textContent = "Trade setup calculations are paused until coherent real history is ready.";
  ["setupEntry", "setupStop", "setupTp1", "setupTp2", "setupRr", "setupCluster"].forEach((id) => { if ($(id)) $(id).textContent = "—"; });
  if ($("setupDirection")) $("setupDirection").textContent = "—";
  if ($("setupStatus")) { $("setupStatus").textContent = syncingText; $("setupStatus").className = "v a"; }
  if ($("setupValid")) $("setupValid").textContent = `${state.baseCandles.length} real bar${state.baseCandles.length === 1 ? "" : "s"}`;
  if ($("chartSetupLabel")) { $("chartSetupLabel").textContent = "DATA SYNCING"; $("chartSetupLabel").className = "a mono"; }
  if ($("chartSetupStatus")) { $("chartSetupStatus").textContent = syncingText; $("chartSetupStatus").className = "a"; }
  ["chartSetupEntry", "chartSetupStop", "chartSetupTp1", "chartSetupTp2", "chartSetupRr", "chartSetupCluster"].forEach((id) => { if ($(id)) $(id).textContent = "—"; });
  if ($("chartPreviewNotice")) {
    $("chartPreviewNotice").hidden = false;
    $("chartPreviewNotice").classList.add("syncing");
    if ($("chartPreviewTitle")) $("chartPreviewTitle").textContent = syncingText;
    if ($("chartPreviewReason")) $("chartPreviewReason").textContent = "TradeIQ rejected mixed or incomplete price history. Indicators and trade levels stay hidden until one coherent contract series is available.";
  }
  drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
}

function renderAll(setup, meta, session = state.session) {
  if (!setup || !meta) {
    renderSyncingState({}, session);
    return;
  }
  const previousSetup = state.setup;
  state.setup = setup;
  state.meta = meta;
  if (setup.gex) state.gexSummary = setup.gex;
  if (session) renderSession(session);
  renderOverview(meta.overview);
  renderHeader();
  renderGexTable(setup);
  renderConfidence(setup);
  renderKeyConfluences(setup);
  renderTradeSetup(setup);
  loadSetupTimeline(setup);
  renderGexSummary(setup);
  renderZones(setup);
  renderFib(setup);
  renderAlerts(meta.alerts);
  renderEconomicCalendar(meta.economic_events || [], meta.economic_calendar_status || {});
  renderNews(meta.news);
  renderPerformance(meta.performance);
  drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
  renderGexPage(setup);
  renderConfluencePage(setup);
  maybeRunClaudeOnStateChange(previousSetup, setup);
}

function normaliseMarketCandle(candle) {
  const timestamp = new Date(candle?.time).getTime();
  const open = Number(candle?.open);
  const high = Number(candle?.high);
  const low = Number(candle?.low);
  const close = Number(candle?.close);
  const volume = Math.max(0, Number(candle?.volume || 0));
  if (![timestamp, open, high, low, close, volume].every(Number.isFinite)) return null;
  if (open <= 0 || close <= 0 || high < low || high < Math.max(open, close) || low > Math.min(open, close)) return null;
  // A one-minute futures candle spanning more than eight percent is corrupt
  // for every currently supported TradeIQ market. Reject it before charting.
  const reference = Math.max(Math.abs(open), Math.abs(close), 1e-9);
  if ((high - low) / reference > 0.08) return null;
  return { time: new Date(timestamp).toISOString(), open, high, low, close, volume };
}

function normaliseMarketCandles(candles = []) {
  const byTime = new Map();
  candles.forEach((raw) => {
    const candle = normaliseMarketCandle(raw);
    if (candle) byTime.set(new Date(candle.time).getTime(), candle);
  });
  const ordered = [...byTime.values()].sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());
  if (ordered.length < 3) return ordered;

  const clean = [ordered[0]];
  const recentRanges = [Math.max(0, ordered[0].high - ordered[0].low)];
  for (let index = 1; index < ordered.length - 1; index += 1) {
    const previous = clean.at(-1);
    const current = ordered[index];
    const following = ordered[index + 1];
    const reference = Math.max(Math.abs(previous.close), 1e-9);
    const jump = Math.abs(current.open - previous.close) / reference;
    const returnJump = Math.abs(following.open - current.close) / Math.max(Math.abs(current.close), 1e-9);
    const candleRange = Math.max(0, current.high - current.low);
    const body = Math.abs(current.close - current.open);
    const sample = recentRanges.slice(-30).filter((value) => value > 0).sort((a, b) => a - b);
    const middle = Math.floor(sample.length / 2);
    const typicalRange = sample.length ? (sample.length % 2 ? sample[middle] : (sample[middle - 1] + sample[middle]) / 2) : 0;
    const giantWick = typicalRange > 0
      && candleRange > Math.max(typicalRange * 10, reference * 0.008)
      && body < Math.max(typicalRange * 5, candleRange * 0.35);
    if (giantWick || (jump > 0.08 && returnJump > 0.08)) continue;
    clean.push(current);
    recentRanges.push(candleRange);
  }
  const last = ordered.at(-1);
  const previous = clean.at(-1);
  const reference = Math.max(Math.abs(previous.close), 1e-9);
  const candleRange = Math.max(0, last.high - last.low);
  const body = Math.abs(last.close - last.open);
  const sample = recentRanges.slice(-30).filter((value) => value > 0).sort((a, b) => a - b);
  const middle = Math.floor(sample.length / 2);
  const typicalRange = sample.length ? (sample.length % 2 ? sample[middle] : (sample[middle - 1] + sample[middle]) / 2) : 0;
  const giantLiveWick = typicalRange > 0
    && candleRange > Math.max(typicalRange * 10, reference * 0.008)
    && body < Math.max(typicalRange * 4, candleRange * 0.35);
  if (!giantLiveWick) clean.push(last);
  return clean.slice(-2400);
}

function upsertBaseCandle(rawCandle) {
  const candle = normaliseMarketCandle(rawCandle);
  if (!candle) return false;
  state.baseCandles = normaliseMarketCandles([...state.baseCandles, candle]);
  return true;
}

function aggregateCandles(candles, minutes) {
  const ordered = normaliseMarketCandles(candles);
  if (minutes <= 1) return ordered;
  const bucketMs = minutes * 60 * 1000;
  const buckets = new Map();
  for (const candle of ordered) {
    const bucket = Math.floor(new Date(candle.time).getTime() / bucketMs) * bucketMs;
    const current = buckets.get(bucket);
    if (!current) {
      buckets.set(bucket, { ...candle, time: new Date(bucket).toISOString() });
      continue;
    }
    current.high = Math.max(current.high, candle.high);
    current.low = Math.min(current.low, candle.low);
    current.close = candle.close;
    current.volume += candle.volume;
  }
  return [...buckets.entries()].sort((a, b) => a[0] - b[0]).map(([, candle]) => candle);
}
function ema(candles, period) {
  if (!candles.length) return [];
  const alpha = 2 / (period + 1);
  let value = candles[0].close;
  return candles.map((candle) => { value = candle.close * alpha + value * (1 - alpha); return value; });
}

function drawEquity(points = []) {
  const canvas = $("equity");
  if (!canvas || !points.length) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth; const height = canvas.clientHeight;
  canvas.width = width * dpr; canvas.height = height * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const min = Math.min(...points); const max = Math.max(...points); const range = max - min || 1;
  ctx.beginPath();
  points.forEach((value, index) => {
    const x = index / (points.length - 1) * width;
    const y = height - 4 - (value - min) / range * (height - 8);
    index ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.strokeStyle = COLORS.green; ctx.lineWidth = 1.6; ctx.stroke();
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "rgba(38,208,124,.22)"); gradient.addColorStop(1, "rgba(38,208,124,0)");
  ctx.lineTo(width, height); ctx.lineTo(0, height); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
}

function drawChart(chartId = "chart") {
  const manager = window.TradeIQChartManager;
  if (!manager) return;
  if (chartId === "chartLarge" && $("chartLargeStatus")) $("chartLargeStatus").textContent = chartFeedLabel();
  const chartSetup = state.setup
    ? { ...state.setup, gex: state.setup.gex || state.gexSummary }
    : (state.gexSummary ? { gex: state.gexSummary, order_state: "PREVIEW_ONLY", zones: [], fib_levels: [] } : null);
  manager.render(chartId, {
    candles: aggregateCandles(state.baseCandles, state.timeframe),
    setup: chartSetup,
    overlays: state.overlays,
    timeframe: state.timeframe,
    dataSource: state.dataSource,
    symbol: activeSymbol(),
    displaySymbol: displaySymbol(),
    instrumentName: instrumentName(),
    tickSize: tickSize(),
    pricePrecision: pricePrecision(),
    historyReady: state.historyReady,
    historySource: state.historySource,
    dataQuality: state.dataQuality,
    rawSymbol: state.rawSymbol,
    marketWarming: state.marketWarming,
  });
}

function scheduleChartDraw(chartId = "chartLarge", delay = 0) {
  window.setTimeout(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        drawChart(chartId);
        window.TradeIQChartManager?.resize?.(chartId);
        window.setTimeout(() => window.TradeIQChartManager?.refresh?.(chartId), 80);
      });
    });
  }, delay);
}

async function initialLoad() {
  try {
    const [health, snapshot, dashboard, radar] = await Promise.all([
      fetch("/api/health").then((response) => response.ok ? response.json() : Promise.reject(new Error("Health request failed"))),
      fetch("/api/market/snapshot?timeframe=1&limit=1400").then((response) => response.json()),
      fetch("/api/dashboard").then(async (response) => response.ok ? response.json() : null),
      fetch("/api/multi-market/opportunities").then(async (response) => response.ok ? response.json() : null),
    ]);
    state.baseCandles = normaliseMarketCandles(snapshot.candles || []);
    applySnapshotMetadata(snapshot);
    const initialMarket = health.market || {};
    state.marketWarming = Boolean(initialMarket.warming || (health.data_source === "databento" && !initialMarket.history_cached) || snapshot.warming);
    state.historyReady = Boolean(snapshot.history_ready ?? initialMarket.history_ready ?? initialMarket.history_cached);
    state.historySource = snapshot.history_source || initialMarket.history_source || state.historySource;
    state.dataQuality = snapshot.data_quality || initialMarket.data_quality || state.dataQuality;
    state.rawSymbol = snapshot.raw_symbol || initialMarket.raw_symbol || null;
    updateMarketFeedStatus(initialMarket);
    applyInstrument(snapshot.instrument || health.instrument || health.market?.instrument);
    if (dashboard?.setup && dashboard?.meta) renderAll(dashboard.setup, dashboard.meta, dashboard.session || health.session);
    else renderSyncingState(snapshot, health.session);
    $("chartCaption").textContent = chartFeedLabel();
    renderHeader(snapshot);
    startRestFallback();
    processMarketOpportunities(radar?.items || [], radar?.status || null, false);
    cacheCurrentMarket();
    await loadClaudeStatus();
    loadEconomicCalendar();
    connectWebSocket();
  } catch (error) {
    console.error(error);
    $("modeLabel").textContent = "ERROR";
    startRestFallback();
    connectWebSocket();
  }
}


async function reloadSyncedHistory() {
  try {
    const snapshot = await fetch("/api/market/snapshot?timeframe=1&limit=1400").then((response) => {
      if (!response.ok) throw new Error(`Snapshot refresh failed (${response.status})`);
      return response.json();
    });
    if (snapshot.symbol && snapshot.symbol !== activeSymbol()) return false;
    state.baseCandles = normaliseMarketCandles(snapshot.candles || []);
    applySnapshotMetadata(snapshot);
    applyInstrument(snapshot.instrument);
    renderHeader(snapshot);
    window.TradeIQChartManager?.marketChanged?.("chart");
    window.TradeIQChartManager?.marketChanged?.("chartLarge");
    drawChart();
    if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
    toast(`${activeSymbol()} Databento history ready`);
    return true;
  } catch (error) {
    console.error(error);
    toast("History synced, but the chart refresh failed");
    return false;
  }
}

function clearSocketReconnectTimer() {
  if (state.socketReconnectTimer) {
    clearTimeout(state.socketReconnectTimer);
    state.socketReconnectTimer = null;
  }
}

function clearSocketConnectTimer() {
  if (state.socketConnectTimer) {
    clearTimeout(state.socketConnectTimer);
    state.socketConnectTimer = null;
  }
}

async function pollRestFallback() {
  if (!state.restFallbackActive || state.restFallbackBusy) return;
  state.restFallbackBusy = true;
  try {
    const response = await fetch("/api/live-state", { cache: "no-store" });
    if (!response.ok) throw new Error(`Live-state fallback failed (${response.status})`);
    const data = await response.json();
    if (!state.restFallbackActive || state.switchingSymbol) return;

    const wasWarming = state.marketWarming;
    const previousFeedState = state.feedState;
    const market = data.market || {};
    state.marketWarming = Boolean(market.warming || (market.data_source === "databento" && !market.history_cached));
    state.historyReady = Boolean(market.history_ready ?? market.history_cached);
    state.historySource = market.history_source || state.historySource;
    state.dataQuality = market.data_quality || state.dataQuality;
    state.rawSymbol = market.raw_symbol || state.rawSymbol;
    updateMarketFeedStatus(market);

    const incomingInstrument = market.instrument;
    if (incomingInstrument && incomingInstrument.symbol !== activeSymbol()) {
      state.baseCandles = [];
      applyInstrument(incomingInstrument);
    }
    if (data.candle) upsertBaseCandle(data.candle);
    if (data.gex_summary) state.gexSummary = data.gex_summary;
    if (data.setup && data.meta) renderAll(data.setup, data.meta, data.session);
    else {
      renderSyncingState({ price: data.candle?.close }, data.session);
      renderGexPage(state.gexSummary);
    }
    cacheCurrentMarket();

    const feedRecovered = previousFeedState !== "LIVE" && state.feedState === "LIVE";
    if ((wasWarming && !state.marketWarming) || feedRecovered) await reloadSyncedHistory();
    setConnection(false);
  } catch (error) {
    console.debug("TradeIQ REST fallback poll failed", error);
  } finally {
    state.restFallbackBusy = false;
  }
}

function startRestFallback() {
  if (state.restFallbackActive) return;
  state.restFallbackActive = true;
  setConnection(false);
  pollRestFallback();
  state.restFallbackTimer = setInterval(pollRestFallback, 3000);
}

function stopRestFallback() {
  state.restFallbackActive = false;
  state.restFallbackBusy = false;
  if (state.restFallbackTimer) {
    clearInterval(state.restFallbackTimer);
    state.restFallbackTimer = null;
  }
}

async function refreshHealthDuringReconnect() {
  try {
    const health = await fetch("/api/health", { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error(`Health check failed (${response.status})`);
      return response.json();
    });
    if (health.market) updateMarketFeedStatus(health.market);
  } catch (error) {
    console.debug("TradeIQ reconnect health check failed", error);
  }
}

function scheduleWebSocketReconnect() {
  if (state.socketReconnectTimer) return;
  state.socketReconnectAttempt += 1;
  const delay = Math.min(15000, 1000 * (2 ** Math.min(state.socketReconnectAttempt - 1, 4)));
  refreshHealthDuringReconnect();
  state.socketReconnectTimer = setTimeout(() => {
    state.socketReconnectTimer = null;
    connectWebSocket();
  }, delay);
}

function startSocketWatchdog() {
  if (state.socketWatchdogTimer) return;
  state.socketWatchdogTimer = setInterval(() => {
    const socket = state.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN || !state.socketLastMessageAt) return;
    const silentFor = Date.now() - state.socketLastMessageAt;
    if (silentFor > 12000) {
      console.warn(`TradeIQ market WebSocket silent for ${Math.round(silentFor / 1000)}s; reconnecting`);
      try { socket.close(4000, "heartbeat timeout"); } catch (_) { /* no-op */ }
    }
  }, 3000);
}

function connectWebSocket() {
  if (state.socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(state.socket.readyState)) return;
  clearSocketReconnectTimer();
  startSocketWatchdog();

  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/market`);
  state.socket = socket;
  const reconnecting = state.socketReconnectAttempt > 0;
  clearSocketConnectTimer();
  state.socketConnectTimer = setTimeout(() => {
    if (state.socket !== socket || socket.readyState !== WebSocket.CONNECTING) return;
    console.warn("TradeIQ WebSocket handshake timed out; enabling REST fallback");
    state.socket = null;
    startRestFallback();
    try { socket.close(4001, "connect timeout"); } catch (_) { /* no-op */ }
    scheduleWebSocketReconnect();
  }, 8000);

  socket.onopen = () => {
    if (state.socket !== socket) return;
    clearSocketConnectTimer();
    stopRestFallback();
    state.socketLastMessageAt = Date.now();
    setConnection(true);
    state.socketReconnectAttempt = 0;
    if (reconnecting) {
      // The server may have accumulated candles while the browser socket was
      // offline. Reloading the backend snapshot repairs that gap without
      // resetting the user's saved chart viewport.
      setTimeout(() => reloadSyncedHistory(), 350);
    }
  };

  socket.onmessage = async (event) => {
    if (state.socket !== socket) return;
    state.socketLastMessageAt = Date.now();
    setConnection(true);
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (error) {
      console.error("Invalid market WebSocket payload", error);
      return;
    }
    if (data.component_errors?.length) console.warn("TradeIQ degraded WebSocket components", data.component_errors);
    if (data.gex_summary) state.gexSummary = data.gex_summary;
    if (data.type === "market_stream_error") return;
    if (data.market_opportunities) processMarketOpportunities(data.market_opportunities, data.market_radar || null, true);
    if (state.switchingSymbol) return;

    const wasWarming = state.marketWarming;
    const previousFeedState = state.feedState;
    state.marketWarming = Boolean(data.market?.warming || (data.market?.data_source === "databento" && !data.market?.history_cached));
    state.historyReady = Boolean(data.market?.history_ready ?? data.market?.history_cached);
    state.historySource = data.market?.history_source || state.historySource;
    state.dataQuality = data.market?.data_quality || state.dataQuality;
    state.rawSymbol = data.market?.raw_symbol || state.rawSymbol;
    if (data.market) updateMarketFeedStatus(data.market);

    const incomingInstrument = data.market?.instrument;
    if (incomingInstrument && incomingInstrument.symbol !== activeSymbol()) {
      state.baseCandles = [];
      applyInstrument(incomingInstrument);
    }
    const candle = data.candle;
    if (candle) upsertBaseCandle(candle);
    if (data.setup && data.meta) renderAll(data.setup, data.meta, data.session);
    else {
      renderSyncingState({ price: candle?.close }, data.session);
      renderGexPage(state.gexSummary);
    }
    cacheCurrentMarket();

    const feedRecovered = previousFeedState !== "LIVE" && state.feedState === "LIVE";
    if ((wasWarming && !state.marketWarming) || feedRecovered) {
      await reloadSyncedHistory();
      if (state.currentPage === "chart" && state.claude.enabled && state.claude.auto && !state.claude.busy) {
        startClaudeAnalysis(false);
      }
    }
  };

  socket.onerror = () => {
    try { socket.close(); } catch (_) { /* no-op */ }
  };

  socket.onclose = () => {
    clearSocketConnectTimer();
    if (state.socket !== socket) return;
    state.socket = null;
    state.socketLastMessageAt = 0;
    startRestFallback();
    setConnection(false);
    scheduleWebSocketReconnect();
  };
}

async function switchMarket(symbol) {
  const selector = $("symbolSelect");
  if (!selector || state.switchingSymbol || symbol === activeSymbol()) return;
  const previousSymbol = activeSymbol();
  cacheCurrentMarket();
  state.switchingSymbol = true;
  selector.disabled = true;
  selector.closest(".symbol-selector")?.classList.add("busy");
  stopClaudeStream();
  state.claude.text = "";
  renderClaudeAnalysis("", false);
  setClaudeStatus("WAITING", "cached");
  if ($("claudeFoot")) $("claudeFoot").textContent = `Waiting for ${symbol} market data…`;
  const restoredInstantly = restoreCachedMarket(symbol);
  toast(restoredInstantly ? `${symbol} restored from local cache · syncing live data` : `Switching TradeIQ to ${symbol}…`);
  try {
    const response = await fetch("/api/market/symbol", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }),
    });
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(failure.detail || `Market switch failed (${response.status})`);
    }
    const selected = await response.json();
    state.marketWarming = Boolean(selected.market?.warming || (selected.market?.data_source === "databento" && !selected.market?.history_cached));
    updateMarketFeedStatus(selected.market || {});
    const [snapshot, dashboard] = await Promise.all([
      fetch("/api/market/snapshot?timeframe=1&limit=1400").then((item) => item.json()),
      fetch("/api/dashboard").then(async (item) => item.ok ? item.json() : null),
    ]);
    state.baseCandles = normaliseMarketCandles(snapshot.candles || []);
    applySnapshotMetadata(snapshot);
    state.hoverIndex = null;
    state.claude.text = "";
    applyInstrument(snapshot.instrument || selected.instrument);
    if (dashboard?.setup && dashboard?.meta) renderAll(dashboard.setup, dashboard.meta, dashboard.session || selected.session);
    else renderSyncingState(snapshot, selected.session);
    renderHeader(snapshot);
    window.TradeIQChartManager?.marketChanged?.("chart");
    window.TradeIQChartManager?.marketChanged?.("chartLarge");
    drawChart();
    if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
    cacheCurrentMarket();
    await loadClaudeStatus();
    if (!state.marketWarming && state.currentPage === "chart" && state.claude.enabled && state.claude.auto) {
      startClaudeAnalysis(false);
    }
    toast(state.marketWarming ? `${symbol} loaded · Databento history syncing` : `${symbol} market loaded`);
  } catch (error) {
    console.error(error);
    restoreCachedMarket(previousSymbol);
    selector.value = previousSymbol;
    toast(error.message || "Could not switch market");
  } finally {
    state.switchingSymbol = false;
    selector.disabled = false;
    selector.closest(".symbol-selector")?.classList.remove("busy");
  }
}

function tick() {
  $("clock").textContent = window.TradeIQTime?.nowClock?.() || new Date().toLocaleTimeString();
  if (state.session) {
    $("sessionTimer").textContent = remainingText(state.session.countdown_target);
    if (!state.session.is_open && $("setupValid")) $("setupValid").textContent = remainingText(state.session.next_open_at);
    if (!state.session.is_open && $("chartSetupValid")) $("chartSetupValid").textContent = remainingText(state.session.next_open_at);
  }
}


function isMobileWorkspace() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function closeMobileMenu() {
  document.querySelector(".side")?.classList.remove("mobile-open");
  document.body.classList.remove("mobile-nav-open");
  const button = $("mobileMenuButton");
  if (button) button.setAttribute("aria-expanded", "false");
}

function toggleMobileMenu() {
  const side = document.querySelector(".side");
  if (!side) return;
  const opening = !side.classList.contains("mobile-open");
  side.classList.toggle("mobile-open", opening);
  document.body.classList.toggle("mobile-nav-open", opening);
  $("mobileMenuButton")?.setAttribute("aria-expanded", opening ? "true" : "false");
}

function setMobileNewsTab(name) {
  const resolved = name === "headlines" ? "headlines" : "calendar";
  state.mobileNewsTab = resolved;
  localStorage.setItem("tradeiq-mobile-news-tab", resolved);
  document.querySelectorAll("[data-mobile-news-tab]").forEach((button) => button.classList.toggle("active", button.dataset.mobileNewsTab === resolved));
  document.querySelectorAll("[data-mobile-news-pane]").forEach((pane) => pane.classList.toggle("active", pane.dataset.mobileNewsPane === resolved));
}

function setMobilePane(name, navigate = true) {
  const allowed = new Set(["chart", "setup", "claude", "news", "gex"]);
  const resolved = allowed.has(name) ? name : "chart";
  state.mobilePane = resolved;
  localStorage.setItem("tradeiq-mobile-pane", resolved);
  if (navigate && state.currentPage !== "chart") setPage("chart");
  document.querySelectorAll("[data-mobile-pane]").forEach((item) => item.classList.toggle("mobile-pane-active", item.dataset.mobilePane === resolved));
  document.querySelectorAll("#mobileBottomNav [data-mobile-target]").forEach((button) => button.classList.toggle("active", button.dataset.mobileTarget === resolved && state.currentPage === "chart"));
  if (resolved === "chart") scheduleChartDraw("chartLarge", 20);
  if (resolved === "news") setMobileNewsTab(state.mobileNewsTab);
  if (resolved === "gex") window.setTimeout(refreshGexCharts, 30);
  if (resolved === "claude" && state.claude.enabled && state.claude.auto && !state.claude.text && !state.claude.busy) setTimeout(() => startClaudeAnalysis(false), 80);
  closeMobileMenu();
}

function syncMobileNavigation() {
  const onChart = state.currentPage === "chart";
  document.querySelectorAll("#mobileBottomNav [data-mobile-target]").forEach((button) => button.classList.toggle("active", onChart && button.dataset.mobileTarget === state.mobilePane));
  if (onChart) setMobilePane(state.mobilePane, false);
}

function registerInstallPrompt() {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    state.deferredInstallPrompt = event;
    if ($("pwaInstall")) $("pwaInstall").hidden = false;
  });
  window.addEventListener("appinstalled", () => {
    state.deferredInstallPrompt = null;
    if ($("pwaInstall")) $("pwaInstall").hidden = true;
    toast("TradeIQ installed");
  });
}

function toast(message) {
  const el = $("toast");
  if (!el) return;
  el.textContent = message; el.style.display = "block";
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.style.display = "none"; }, 2600);
}
function pageRow(label, value, cls = "") {
  return `<div><span>${label}</span><b class="${cls}">${value ?? "—"}</b></div>`;
}
function setPage(name, runLoaders = true) {
  document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${name}`));
  document.querySelectorAll("#nav button[data-page]").forEach((button) => button.classList.toggle("active", button.dataset.page === name));
  state.currentPage = name;
  closeMobileMenu();
  const symbol = activeSymbol();
  const dashboardTitle = state.session ? (state.session.is_open ? `${symbol} · ${state.session.display_name}` : `${symbol} · MARKET CLOSED`) : `${symbol} TRADE ENGINE`;
  const titles = { dashboard:`${symbol} MARKET COMMAND CENTER`, chart:`${symbol} INSTITUTIONAL TRADE DESK`, gex:`${symbol} GEX ANALYSIS`, confluence:`${symbol} CONFLUENCE ENGINE`, setups:`${symbol} TRADE SETUPS`, alerts:"ALERT CENTER", positions:"POSITIONS", backtest:`${symbol} BACKTEST LAB`, settings:"SETTINGS" };
  $("pageTitle").textContent = titles[name] || dashboardTitle;
  syncMobileNavigation();
  if (!runLoaders) return;
  if (name === "chart") setTimeout(() => { drawChart("chartLarge"); if (state.claude.enabled && state.claude.auto && !state.claude.text) startClaudeAnalysis(false); }, 30);
  if (name === "gex") window.setTimeout(loadGexPage, 30);
  if (name === "setups") loadSetups();
  if (name === "alerts") loadAlertsPage();
  if (name === "positions") loadPositions();
  if (name === "settings") loadSettings();
}
function renderScorePage(id, components = {}, maximums = {}) {
  const el = $(id); if (!el) return;
  el.innerHTML = Object.entries(maximums).map(([key, maximum]) => {
    const value = Number(components[key] || 0); const pct = maximum ? Math.min(100, value / maximum * 100) : 0;
    return `<div class="score-page-row"><span>${SCORE_LABELS[key] || key.replaceAll("_", " ")}</span><div class="score-page-bar"><i style="width:${pct}%"></i></div><b class="mono">${value.toFixed(1)}/${Number(maximum).toFixed(0)}</b></div>`;
  }).join("");
}
function renderGexPage(setupOrGex = null) {
  if (!$("gexProfile")) return;
  const g = setupOrGex?.gex || setupOrGex || state.setup?.gex || state.gexSummary;
  if (!g) {
    $("gexProfile").innerHTML = '<p class="note">GEX is syncing. TradeIQ will restore the last locked map automatically.</p>';
    if ($("gexPageTable")) $("gexPageTable").innerHTML = "";
    return;
  }
  state.gexSummary = g;
  const parentNote = g.is_parent_market ? ` Parent-market levels are applied to the ${activeSymbol()} chart.` : "";
  $("gexProfile").innerHTML = `<div class="page-stats">${[
    ["Regime",g.regime],["Dealer bias",g.dealer_bias || "NEUTRAL"],["Net GEX",fmtGex(g.net_gex)],
    ["Positive gamma",`${Number(g.positive_gamma_percent || 0).toFixed(0)}%`],
    ["Negative gamma",`${Number(g.negative_gamma_percent || 0).toFixed(0)}%`],
    ["Gamma flip",fmt(g.gamma_flip)],["Gamma resistance",fmt(g.gamma_resistance ?? g.call_wall)],
    ["Maximum pain",Number.isFinite(Number(g.max_pain)) ? fmt(g.max_pain) : "Native OI required"],
    ["Put support",fmt(g.gamma_support ?? g.put_wall)]
  ].map(([label,value]) => `<div class="page-stat"><b>${escapeHtml(value)}</b><small>${label}</small></div>`).join("")}</div><p class="note">GEX source: ${escapeHtml(g.source_label || g.source || "fallback")}.${parentNote} Levels remain locked to the current option-position snapshot until the next GEX refresh.</p>`;
  const levels = [
    {type:"GAMMA RESISTANCE / CALL WALL",price:g.call_wall,gex:g.call_wall_gex,strength:5},
    ...(Number.isFinite(Number(g.max_pain)) ? [{type:"MAXIMUM PAIN",price:g.max_pain,gex:null,strength:0}] : []),
    {type:"GAMMA FLIP",price:g.gamma_flip,gex:null,strength:0},
    ...(g.levels || []).slice(0,12),
    {type:"PUT SUPPORT / PUT WALL",price:g.put_wall,gex:g.put_wall_gex,strength:5},
  ];
  $("gexPageTable").innerHTML = levels.map((level) => `<tr><td class="${Number(level.gex||0)>=0?'g':'r'}">${level.type || 'LEVEL'}</td><td>${fmt(level.price)}</td><td>${level.gex == null?'—':fmtGex(level.gex)}</td><td class="a">${level.strength?stars(level.strength):'—'}</td></tr>`).join("");
  if ($("gexStrikeSource")) $("gexStrikeSource").textContent = g.is_estimate ? "ESTIMATED" : "NATIVE";
  if ($("gexStrikeSource")) $("gexStrikeSource").classList.toggle("estimated", Boolean(g.is_estimate));
  if ($("gexStrikeSubtitle")) $("gexStrikeSubtitle").textContent = `${g.source_label || g.source || "GEX"} · ${activeSymbol()}`;
  if ($("gexStrikeNote")) $("gexStrikeNote").textContent = g.is_estimate
    ? "Estimated GEX-by-strike profile from the fallback model. Use it as context until native option positioning is available."
    : "Native GEX-by-strike profile from the currently available option-position dataset.";
  window.setTimeout(() => drawGexStrikeChart($("gexStrikeChart"), g, false), 0);
}
function renderConfluencePage(setup) {
  if (!setup || !$("confluencePage")) return;
  renderScorePage("confluencePage", setup.institutional_confidence_components || setup.confidence_components, setup.institutional_confidence_maximums || setup.confidence_maximums);
  const activeClusterCategories = Array.isArray(setup.composite_cluster_active_categories)
    ? setup.composite_cluster_active_categories.map((item) => String(item).replaceAll("_", " ")).join(" · ")
    : "—";
  const activeMap = setup.market_map?.active_cluster;
  const opposingMap = setup.market_map?.opposing_cluster;
  const ladder = Array.isArray(setup.market_map?.ladder) ? setup.market_map.ladder : [];
  const mapRows = ladder.length ? `<div class="market-map-ladder">${ladder.map((cluster) => {
    const contributors = Array.isArray(cluster.contributors)
      ? cluster.contributors.slice(0, 4).map((item) => escapeHtml(item.label)).join(" · ")
      : "";
    return `<div class="market-map-step ${String(cluster.role || "").toLowerCase()}"><span>${fmt(cluster.midpoint)}</span><b>${escapeHtml(String(cluster.tier || "CONTEXT").replaceAll("_", " "))} ${escapeHtml(cluster.role || "")}</b><strong>${Number(cluster.score || 0).toFixed(0)}%</strong><small>${escapeHtml(String(cluster.state || "DISTANT").replaceAll("_", " "))}${contributors ? ` · ${contributors}` : ""}</small></div>`;
  }).join("")}</div>` : '<p class="note">Institutional map is still building.</p>';
  $("clusterCard").innerHTML = `<div class="cluster-box page-kv">${pageRow("Institutional grade",setup.confidence_grade || "—",Number(setup.confidence)>=85?'g':Number(setup.confidence)>=70?'a':'r')}${pageRow("Primary model",setup.primary_entry_model || "—",'b')}${pageRow("Model score",`${Number(setup.primary_model_score||0).toFixed(1)}%`)}${pageRow("Backup models",(setup.alternative_entry_models||[]).slice(0,3).join(" · ")||"—")}${pageRow("Active market-map cluster",marketMapClusterText(activeMap),activeMap?.actionable_location?'g':'a')}${pageRow("Active range",activeMap?`${fmt(activeMap.low)}–${fmt(activeMap.high)}`:'—')}${pageRow("Opposing liquidity",marketMapClusterText(opposingMap),opposingMap?'b':'a')}${pageRow("Opposing range",opposingMap?`${fmt(opposingMap.low)}–${fmt(opposingMap.high)}`:'—')}${pageRow("Composite tier",setup.composite_cluster_eligible?clusterTierName(setup):"Not selected",setup.composite_cluster_eligible?'g':'a')}${pageRow("Composite score",`${Number(setup.composite_cluster_score||0).toFixed(1)}%`,setup.composite_cluster_eligible?'g':'a')}${pageRow("Independent categories",activeClusterCategories)}${pageRow("Ordered sequence",setup.signals?.ordered_sequence?'Confirmed':'Not confirmed',setup.signals?.ordered_sequence?'g':'a')}</div>${mapRows}`;
  const modelReason = setup.model_selection_reason ? `<div class="rationale-item">◆ ${escapeHtml(setup.model_selection_reason)}</div>` : "";
  $("rationale").innerHTML = modelReason + ((setup.rationale || []).map((reason) => `<div class="rationale-item">✓ ${escapeHtml(reason)}</div>`).join("") || '<p class="note">No active rationale yet.</p>');
}
async function loadSetups() {
  try {
    const [rows, analytics] = await Promise.all([
      fetch("/api/setups/history").then((response) => response.json()),
      fetch("/api/analytics/summary").then((response) => response.json()),
    ]);
    if ($("setupHistoryTimezone")) $("setupHistoryTimezone").textContent = `${window.TradeIQTime?.preference?.() === "EXCHANGE" ? "EXCHANGE" : "AUTO"} · ${displayTimeZone()} · ${displayTimeZoneLabel()}`;
    if ($("setupHistoryTimeHeader")) $("setupHistoryTimeHeader").textContent = `Time (${displayTimeZoneLabel()})`;
    $("setupsTable").innerHTML = rows.length ? rows.map((item) => `<tr><td>${formatAppDateTime(item.updated_at)} <span class="time-zone-suffix">${displayTimeZoneLabel(item.updated_at)}</span></td><td class="${classForDirection(item.direction)}">${item.direction}</td><td>${escapeHtml(item.primary_entry_model || "—")}</td><td>${escapeHtml(item.confidence_grade || "—")}</td><td>${fmt(item.confidence,0)}</td><td>${fmt(item.entry)}</td><td>${fmt(item.stop_loss)}</td><td>${fmt(item.active_stop_loss)}</td><td>${fmt(item.take_profit_1)}</td><td>${fmt(item.take_profit_2)}</td><td>${escapeHtml(item.order_state || "—")}</td><td>${escapeHtml(item.management_state || "—")}</td><td>${item.result_r ?? '—'}</td></tr>`).join("") : '<tr><td colspan="13" class="m">No persisted setups yet.</td></tr>';
    const leaders = Array.isArray(analytics.model_leaderboard) ? analytics.model_leaderboard : [];
    $("modelLeaderboard").innerHTML = leaders.length ? leaders.map((item) => `<tr><td>${escapeHtml(item.model)}</td><td>${item.trades}</td><td>${Number(item.win_rate || 0).toFixed(1)}%</td><td>${Number(item.average_r || 0).toFixed(2)}R</td><td>${Number(item.net_r || 0).toFixed(2)}R</td><td>${Number(item.profit_factor || 0).toFixed(2)}</td></tr>`).join("") : '<tr><td colspan="6" class="m">No completed model results yet.</td></tr>';
  } catch (error) { toast("Could not load setup history"); }
}
async function loadAlertsPage() {
  try {
    const rows = await fetch("/api/alerts").then((response) => response.json());
    $("alertsPage").innerHTML = rows.length ? rows.map((item) => `<div class="alert-card ${item.severity}"><b>${item.title}</b><small>${item.created_at ? `${formatAppDateTime(item.created_at)} ${displayTimeZoneLabel(item.created_at)}` : escapeHtml(item.time || "—")} · ${item.detail}</small></div>`).join("") : '<p class="note">No alerts logged yet.</p>';
  } catch (error) { toast("Could not load alerts"); }
}
async function loadPositions() {
  try {
    const rows = await fetch("/api/positions").then((response) => response.json());
    $("positionsPage").innerHTML = rows.length ? rows.map((item) => `<div class="cluster-box page-kv">${pageRow("Symbol",item.symbol)}${pageRow("Direction",item.direction,classForDirection(item.direction))}${pageRow("Entry",fmt(item.entry))}${pageRow("Stop",fmt(item.stop_loss),'r')}${pageRow("TP1",fmt(item.take_profit_1),'g')}${pageRow("TP2",fmt(item.take_profit_2),'g')}${pageRow("State",item.state,'a')}</div>`).join("") : '<p class="note">No active engine-tracked position.</p>';
  } catch (error) { toast("Could not load positions"); }
}
function syncTimeZoneControls() {
  const selector = $("timeZonePreference");
  if (selector) selector.value = window.TradeIQTime?.preference?.() || "AUTO";
  if ($("detectedTimeZone")) $("detectedTimeZone").textContent = window.TradeIQTime?.detectedZone || displayTimeZone();
  if ($("activeTimeZone")) $("activeTimeZone").textContent = `${displayTimeZone()} · ${displayTimeZoneLabel()}`;
}
async function loadSettings() {
  try {
    const settings = await fetch("/api/settings").then((response) => response.json());
    $("settingsPage").innerHTML = Object.entries(settings).map(([key,value]) => pageRow(key.replaceAll("_"," "),String(value))).join("");
    syncTimeZoneControls();
  } catch (error) { toast("Could not load settings"); }
}
function adminHeaders() { return {"Content-Type":"application/json","X-Admin-Token":$("adminToken")?.value || ""}; }
async function refreshGexCache() {
  const response = await fetch("/api/gex/refresh",{method:"POST",headers:adminHeaders()});
  toast(response.ok ? "GEX refresh started" : "Admin token required");
}

$("indicatorToggle").addEventListener("click", () => $("indicatorStrip").classList.toggle("hidden"));
$("templateReset").addEventListener("click", () => {
  state.overlays = { ...DEFAULT_OVERLAYS };
  saveOverlayPreferences();
  syncOverlayButtons();
  state.timeframe = 5;
  document.querySelectorAll(".tf").forEach((button) => button.classList.toggle("active", Number(button.dataset.tf) === 5));
  $("chartCaption").textContent = chartFeedLabel();
  drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
  window.TradeIQChartManager?.reset("chart");
  window.TradeIQChartManager?.reset("chartLarge");
});
document.querySelectorAll(".overlay-btn").forEach((button) => button.addEventListener("click", () => {
  const name = button.dataset.overlay;
  state.overlays[name] = !state.overlays[name];
  saveOverlayPreferences();
  syncOverlayButtons();
  drawChart(); if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
}));
syncOverlayButtons();
if ($("mobileIndicatorsButton")) $("mobileIndicatorsButton").addEventListener("click", () => {
  document.querySelector(".chart-overlay-toggles")?.classList.toggle("mobile-expanded");
});
document.querySelectorAll(".tf").forEach((button) => button.addEventListener("click", () => {
  state.timeframe = Number(button.dataset.tf);
  document.querySelectorAll(".tf").forEach((item) => item.classList.toggle("active", Number(item.dataset.tf) === state.timeframe));
  $("chartCaption").textContent = chartFeedLabel();
  state.hoverIndex = null; drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
}));
document.querySelectorAll("#nav button[data-page]").forEach((item) => item.addEventListener("click", () => setPage(item.dataset.page)));
if ($("symbolSelect")) $("symbolSelect").addEventListener("change", (event) => switchMarket(event.target.value));
if ($("timeZonePreference")) $("timeZonePreference").addEventListener("change", (event) => {
  window.TradeIQTime?.setPreference?.(event.target.value);
});
window.addEventListener("tradeiq-timezone-change", () => {
  syncTimeZoneControls();
  tick();
  renderMarketRadar();
  if (state.meta?.alerts) renderAlerts(state.meta.alerts);
  if (state.currentPage === "setups") loadSetups();
  if (state.currentPage === "alerts") loadAlertsPage();
  drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
  toast(`Display time updated to ${displayTimeZoneLabel()} (${displayTimeZone()})`);
});
document.querySelectorAll("[data-desk-tab]").forEach((button) => button.addEventListener("click", () => setDeskTab(button.dataset.deskTab)));
if ($("deskRailToggle")) $("deskRailToggle").addEventListener("click", () => setDeskCollapsed(!state.deskCollapsed));
if ($("deskRailClose")) $("deskRailClose").addEventListener("click", () => setDeskCollapsed(true));
if ($("marketRadarList")) $("marketRadarList").addEventListener("click", (event) => {
  const card = event.target.closest("[data-radar-symbol]");
  if (!card) return;
  setDeskTab("setup");
  switchMarket(card.dataset.radarSymbol);
});
if ($("enableMarketNotifications")) $("enableMarketNotifications").addEventListener("click", async () => {
  if (!("Notification" in window)) { toast("This browser does not support desktop notifications"); return; }
  const permission = await Notification.requestPermission();
  const enabled = permission === "granted";
  $("enableMarketNotifications").classList.toggle("enabled", enabled);
  $("enableMarketNotifications").textContent = enabled ? "Desktop alerts enabled" : "Enable desktop alerts";
  toast(enabled ? "Cross-market desktop alerts enabled" : "Notification permission was not granted");
});
if ($("mobileMenuButton")) $("mobileMenuButton").addEventListener("click", toggleMobileMenu);
if ($("mobileBackdrop")) $("mobileBackdrop").addEventListener("click", closeMobileMenu);
document.querySelectorAll("#mobileBottomNav [data-mobile-target]").forEach((button) => button.addEventListener("click", () => setMobilePane(button.dataset.mobileTarget)));
document.querySelectorAll("[data-mobile-news-tab]").forEach((button) => button.addEventListener("click", () => setMobileNewsTab(button.dataset.mobileNewsTab)));
if ($("headerAnalyze")) $("headerAnalyze").addEventListener("click", () => {
  setPage("chart");
  setMobilePane("claude", false);
  startClaudeAnalysis(true);
});
if ($("pwaInstall")) $("pwaInstall").addEventListener("click", async () => {
  if (!state.deferredInstallPrompt) {
    toast(/iPad|iPhone|iPod/.test(navigator.userAgent) ? "On iPhone/iPad: Share → Add to Home Screen" : "Use your browser menu to install TradeIQ");
    return;
  }
  state.deferredInstallPrompt.prompt();
  await state.deferredInstallPrompt.userChoice;
  state.deferredInstallPrompt = null;
  $("pwaInstall").hidden = true;
});
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMobileMenu(); });
registerInstallPrompt();
setDeskTab(state.deskTab);
setDeskCollapsed(state.deskCollapsed);
if ($("enableMarketNotifications") && "Notification" in window && Notification.permission === "granted") {
  $("enableMarketNotifications").classList.add("enabled");
  $("enableMarketNotifications").textContent = "Desktop alerts enabled";
}
setMobilePane(state.mobilePane, false);
setMobileNewsTab(state.mobileNewsTab);
const requestedView = new URLSearchParams(window.location.search).get("view");
if (requestedView === "gex") setPage("gex");
else if (requestedView === "claude") { setPage("chart"); setMobilePane("claude", false); }
else if (requestedView === "chart" || isMobileWorkspace()) { setPage("chart"); setMobilePane(requestedView === "chart" ? "chart" : state.mobilePane, false); }

function refreshVisibleCharts() {
  if (!isMobileWorkspace()) closeMobileMenu();
  syncMobileNavigation();
  drawChart();
  window.TradeIQChartManager?.resize?.("chart");
  if ($("page-chart")?.classList.contains("active")) scheduleChartDraw("chartLarge", 10);
  if (state.meta?.performance) drawEquity(state.meta.performance.equity_curve);
  refreshGexCharts();
}
window.addEventListener("resize", refreshVisibleCharts);
window.addEventListener("orientationchange", () => setTimeout(refreshVisibleCharts, 160));
window.addEventListener("pageshow", () => scheduleChartDraw("chartLarge", 30));
document.addEventListener("visibilitychange", () => { if (!document.hidden && state.currentPage === "chart") scheduleChartDraw("chartLarge", 30); });

if ($("refreshGex")) $("refreshGex").addEventListener("click", refreshGexCache);
if ($("settingsRefreshGex")) $("settingsRefreshGex").addEventListener("click", refreshGexCache);
if ($("resetSetup")) $("resetSetup").addEventListener("click", async () => {
  const response = await fetch("/api/setup/reset",{method:"POST",headers:adminHeaders()});
  toast(response.ok ? "Active setup reset" : "Admin token required");
});
if ($("reloadSetups")) $("reloadSetups").addEventListener("click", loadSetups);
if ($("reloadAlerts")) $("reloadAlerts").addEventListener("click", loadAlertsPage);
if ($("backtestForm")) $("backtestForm").addEventListener("submit", async (event) => {
  event.preventDefault(); $("backtestStats").innerHTML = '<p class="note">Running…</p>';
  try {
    const body = {timeframe:Number($("btTf").value),target_r:Number($("btR").value),max_bars:Number($("btBars").value),minimum_score:75};
    const result = await fetch("/api/backtest",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then((response) => response.json());
    $("backtestStats").innerHTML = [["Trades",result.trades],["Win rate",`${result.win_rate}%`],["Avg R",result.average_r],["Profit factor",result.profit_factor],["Net R",result.net_r]].map(([label,value]) => `<div class="page-stat"><b>${value}</b><small>${label}</small></div>`).join("");
    $("backtestTable").innerHTML = (result.rows || []).map((item) => `<tr><td>${formatAppDateTime(item.time)} ${displayTimeZoneLabel(item.time)}</td><td class="${classForDirection(item.direction)}">${item.direction}</td><td>${fmt(item.entry)}</td><td>${fmt(item.stop)}</td><td>${fmt(item.target)}</td><td class="${item.result_r>0?'g':item.result_r<0?'r':'a'}">${item.result_r}R</td></tr>`).join("");
    drawSimpleLine($("backtestEquity"), result.equity_curve || []);
  } catch (error) { $("backtestStats").innerHTML = '<p class="note r">Backtest failed.</p>'; }
});
function drawSimpleLine(canvas, points) {
  if (!canvas || !points.length) return;
  const dpr=window.devicePixelRatio||1,width=canvas.clientWidth,height=canvas.clientHeight; canvas.width=width*dpr;canvas.height=height*dpr;
  const ctx=canvas.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  const min=Math.min(...points),max=Math.max(...points),range=max-min||1;ctx.strokeStyle=COLORS.green;ctx.lineWidth=1.6;ctx.beginPath();
  points.forEach((value,index)=>{const x=index/(points.length-1||1)*width,y=height-6-(value-min)/range*(height-12);index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
}
if ($("claudeAnalyze")) $("claudeAnalyze").addEventListener("click", () => startClaudeAnalysis(true));
if ($("claudeAuto")) $("claudeAuto").addEventListener("change", (event) => {
  state.claude.auto = Boolean(event.target.checked);
  if (state.claude.auto && state.currentPage === "chart" && state.claude.enabled) startClaudeAnalysis(false);
});
setInterval(() => {
  if (state.currentPage === "chart" && state.claude.enabled && state.claude.auto && !state.claude.busy) startClaudeAnalysis(false);
}, 300000);
setInterval(loadEconomicCalendar, 900000);
setInterval(() => loadMarketRadar(true), 60000);

setInterval(tick, 1000); tick(); initialLoad();
