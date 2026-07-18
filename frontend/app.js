const $ = (id) => document.getElementById(id);
const SCORE_LABELS = {
  trend_alignment: "Trend (EMA 9/21/55)",
  gex_alignment: "GEX Alignment",
  liquidity_sweep: "Liquidity Sweep",
  displacement: "FVG / Displacement",
  ote_overlap: "OTE 0.618–0.786",
  supply_demand: "Supply / Demand Zone",
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
  std_dev_confluence: "Standard-deviation confluence",
  vwap_alignment: "Price aligned with VWAP",
  approaching_wall: "Approaching directional GEX wall",
};
const COLORS = {
  green: "#26D07C", red: "#FF4D5E", amber: "#F5B93B", blue: "#48A3FF",
  purple: "#A98BFF", muted: "#455468", text: "#D8E2F0", line: "#1A2636",
};
const state = {
  baseCandles: [],
  setup: null,
  meta: null,
  timeframe: 5,
  connected: false,
  hoverIndex: null,
  chartMeta: null,
  overlays: { emas: true, gex: true, fib: true, zones: true, trade: true, vwap: true },
};

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function fmtSigned(value, digits = 2) {
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
  const date = new Date(value);
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" });
}
function classForDirection(direction) {
  return direction === "LONG" ? "g" : direction === "SHORT" ? "r" : "m";
}
function stars(strength) {
  const n = Math.max(0, Math.min(5, Number(strength || 0)));
  return "★".repeat(n) + "☆".repeat(5 - n);
}

// Single health light — the one green dot doubles as the system status
// indicator. States: live (green) / warn (amber) / error (red).
// warn = connected but data looks wrong (frozen price, or fell back to
// simulated when live was expected). error = socket down / fetch failing.
function setHealth(status, message) {
  state.connected = status !== "error";
  const dot = $("liveDot");
  const label = $("connectionLabel");
  if (!dot || !label) return;
  const map = {
    live: { text: "LIVE", cls: "g", dotCls: "" },
    warn: { text: message || "DELAYED", cls: "a", dotCls: "warn" },
    error: { text: message || "NO DATA", cls: "r", dotCls: "offline" },
  };
  const s = map[status] || map.error;
  dot.classList.remove("warn", "offline");
  if (s.dotCls) dot.classList.add(s.dotCls);
  label.textContent = s.text;
  label.className = s.cls;
  label.title = message || "";
}

// Backwards-compatible wrapper for existing callers.
function setConnection(connected) {
  if (connected) evaluateHealth(); else setHealth("error", "RECONNECTING");
}

// Decide health from the latest data: are we live, and is the tape moving?
let lastPrice = null;
let lastPriceChangeTs = Date.now();
function evaluateHealth() {
  const price = state.baseCandles.at(-1)?.close;
  const now = Date.now();
  if (price !== undefined && price !== lastPrice) { lastPrice = price; lastPriceChangeTs = now; }

  const marketOpen = typeof marketStatus === "function" ? marketStatus().open : true;
  // If live mode but the engine fell back to simulated, warn.
  if (state.dataMode && state.dataMode !== "LIVE") { setHealth("warn", "SIMULATED"); return; }
  // Price frozen for >90s while the market is open = likely a data problem.
  if (marketOpen && now - lastPriceChangeTs > 90000) { setHealth("warn", "STALE PRICE"); return; }
  setHealth("live");
}

function renderHeader(snapshot) {
  const current = snapshot?.price ?? state.baseCandles.at(-1)?.close;
  if (current === undefined) return;
  const nq = state.meta?.overview?.find((item) => item.symbol === "NQ1!");
  const change = nq?.change ?? snapshot?.change ?? 0;
  const percent = nq?.change_percent ?? snapshot?.change_percent ?? 0;
  $("hdrPrice").textContent = fmt(current);
  $("hdrChg").textContent = `${fmtSigned(change)} (${percent >= 0 ? "+" : ""}${percent.toFixed(2)}%)`;
  $("hdrChg").className = `mono ${change >= 0 ? "g" : "r"}`;
}

function renderOverview(items = []) {
  $("overview").innerHTML = items.map((item) => {
    const cls = item.change_percent >= 0 ? "g" : "r";
    const priceDigits = item.symbol === "YM1!" ? 0 : 2;
    return `<div class="ov-row"><span>${item.symbol}</span><span>${fmt(item.price, priceDigits)} <span class="${cls}">${item.change_percent >= 0 ? "+" : ""}${item.change_percent.toFixed(2)}%</span></span></div>`;
  }).join("") || '<div class="loading">No overview data</div>';
}

function renderGexTable(setup) {
  const gex = setup.gex;
  const rows = [
    { type: "Call Wall", price: gex.call_wall, gex: Math.max(...gex.levels.map((x) => x.gex || 0), 0), strength: 5, cls: "b" },
    ...gex.levels.slice(0, 6).map((level) => ({ ...level, cls: (level.gex || 0) >= 0 ? "g" : "r" })),
    { type: "Gamma Flip", price: gex.gamma_flip, gex: null, strength: 0, cls: "a" },
    { type: "Put Wall", price: gex.put_wall, gex: Math.min(...gex.levels.map((x) => x.gex || 0), 0), strength: 5, cls: "r" },
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

function renderTradeSetup(setup) {
  const confidence = Math.max(0, Math.min(100, Number(setup.confidence)));
  const circumference = 307.9;
  $("gaugeArc").style.strokeDashoffset = String(circumference * (1 - confidence / 100));
  const gaugeColor = confidence >= 70 ? COLORS.green : confidence >= 50 ? COLORS.amber : COLORS.red;
  $("gaugeArc").style.stroke = gaugeColor;
  $("confidencePct").textContent = `${Math.round(confidence)}%`;
  $("confidencePct").style.color = gaugeColor;

  const quality = confidence >= 80 ? "High Confluence" : confidence >= 70 ? "Strong Confluence" : confidence >= 55 ? "Developing Setup" : "Low Confluence";
  $("probabilityLabel").textContent = quality;
  $("probabilityLabel").style.color = gaugeColor;
  const coreKeys = ["trend_alignment", "gex_alignment", "ote_overlap", "supply_demand"];
  const aligned = coreKeys.filter((key) => setup.signals[key]).length;
  $("coreAlignment").textContent = `${aligned} / ${coreKeys.length} core confluences aligned`;

  $("setupLabel").textContent = `${setup.direction} SETUP`;
  $("setupLabel").className = `${classForDirection(setup.direction)} mono setup-side-label`;
  $("setupDirection").textContent = `${setup.direction} ${setup.direction === "LONG" ? "↑" : setup.direction === "SHORT" ? "↓" : ""}`;
  $("setupDirection").className = `v ${classForDirection(setup.direction)}`;
  $("setupEntry").textContent = fmt(setup.entry);
  $("setupStop").textContent = fmt(setup.stop_loss);
  $("setupTp1").textContent = fmt(setup.take_profit_1);
  $("setupTp2").textContent = fmt(setup.take_profit_2);
  $("setupRr").textContent = setup.risk_reward ? `1 : ${Number(setup.risk_reward).toFixed(1)}` : "—";
  $("setupStatus").textContent = setup.status.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (x) => x.toUpperCase());
  $("setupValid").textContent = new Date(setup.valid_until).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "America/New_York" });
}

function renderGexSummary(setup) {
  const gex = setup.gex;
  $("gexRegime").textContent = `${gex.regime.charAt(0)}${gex.regime.slice(1).toLowerCase()} Gamma`;
  $("gexRegime").className = `v ${gex.regime === "POSITIVE" ? "g" : gex.regime === "NEGATIVE" ? "r" : "a"}`;
  $("gammaFlip").textContent = fmt(gex.gamma_flip);
  $("putWall").textContent = fmt(gex.put_wall);
  $("callWall").textContent = fmt(gex.call_wall);
  const price = state.baseCandles.at(-1)?.close ?? 0;
  const above = price >= gex.gamma_flip;
  $("priceVsFlip").textContent = above ? "Above Flip" : "Below Flip";
  $("priceVsFlip").className = `v ${above ? "g" : "r"}`;
  const normalized = 50 + Math.tanh(gex.net_gex / 1e9) * 42;
  $("gexNeedle").style.left = `${Math.max(2, Math.min(98, normalized))}%`;
}

function renderZones(setup) {
  const zones = setup.zones.slice(0, 7);
  $("sdTable").innerHTML = zones.length ? zones.map((zone) => `<tr>
    <td>${zone.timeframe}</td><td class="${zone.kind === "DEMAND" ? "g" : "r"}">${zone.kind[0]}${zone.kind.slice(1).toLowerCase()}</td>
    <td>${fmt(zone.low)}–${fmt(zone.high)}</td><td class="a stars">${stars(zone.strength)}</td></tr>`).join("") : '<tr><td colspan="4" class="m">No fresh zones detected</td></tr>';
}

function renderFib(setup) {
  $("fibTable").innerHTML = setup.fib_levels.map((level) => {
    const cls = Math.abs(level.ratio - 0.705) < 0.001 ? "a" : level.ratio >= 0.618 ? "p" : "m";
    return `<tr><td class="${cls}">${level.ratio.toFixed(3)} · ${level.label}</td><td style="text-align:right" class="${cls}">${fmt(level.price)}</td></tr>`;
  }).join("");
}

function renderAlerts(items = []) {
  const classes = { positive: "g", negative: "r", warning: "a", info: "b" };
  $("alerts").innerHTML = items.map((item) => `<tr class="alert-row"><td>${item.time}</td><td class="${classes[item.severity] || "b"}">${item.title}</td></tr>
    <tr><td colspan="2" class="m" style="border-top:none;padding-top:0;font-size:11px">${item.detail}</td></tr>`).join("");
}
function renderNews(items = []) {
  $("news").innerHTML = items.map((item) => `<tr><td>${item.time}</td><td>${item.event}</td><td class="${item.impact === "High" ? "r" : item.impact === "Med" ? "a" : "m"}" style="text-align:right">${item.impact}</td></tr>`).join("");
}
function renderPerformance(performance) {
  if (!performance) return;
  const header = $("perfHeader");
  if (header) header.textContent = performance.simulated ? "Performance · Simulated" : "Performance · Live Tracked";
  if (!performance.trades) {
    // No closed trades yet — show a clear waiting state instead of zeros.
    $("perfWin").textContent = "—";
    $("perfTrades").textContent = "0";
    $("perfAvgR").textContent = "—";
    $("perfPF").textContent = "—";
    $("perfPnl").textContent = "—";
    drawEquity([0]);
    if (header) header.textContent = "Performance · Awaiting first trade";
    return;
  }
  $("perfWin").textContent = `${performance.win_rate.toFixed(0)}%`;
  $("perfTrades").textContent = performance.trades;
  $("perfAvgR").textContent = `${performance.average_r.toFixed(2)}R`;
  $("perfPF").textContent = performance.profit_factor.toFixed(2);
  $("perfPnl").textContent = `${performance.net_pnl >= 0 ? "+" : ""}${fmt(performance.net_pnl, 0)}`;
  drawEquity(performance.equity_curve);
}

function renderAll(setup, meta, liveTick = false) {
  state.setup = setup;
  state.meta = meta;
  renderOverview(meta.overview);
  renderHeader();
  renderGexTable(setup);
  renderConfidence(setup);
  renderKeyConfluences(setup);
  renderTradeSetup(setup);
  renderGexSummary(setup);
  renderZones(setup);
  renderFib(setup);
  renderAlerts(meta.alerts);
  renderNews(meta.news);
  renderPerformance(meta.performance);
  // On live websocket ticks, update just the last bar + overlays so the
  // user's zoom/pan is preserved. Full redraw only on initial load / TF change.
  if (liveTick) updateChartLive(); else drawChart();
}

function aggregateCandles(candles, minutes) {
  if (minutes <= 1) return candles.slice();
  const bucketMs = minutes * 60 * 1000;
  const result = [];
  let current = null;
  for (const candle of candles) {
    const bucket = Math.floor(new Date(candle.time).getTime() / bucketMs) * bucketMs;
    if (!current || current.bucket !== bucket) {
      if (current) result.push(current.candle);
      current = { bucket, candle: { ...candle, time: new Date(bucket).toISOString() } };
    } else {
      current.candle.high = Math.max(current.candle.high, candle.high);
      current.candle.low = Math.min(current.candle.low, candle.low);
      current.candle.close = candle.close;
      current.candle.volume += candle.volume;
    }
  }
  if (current) result.push(current.candle);
  return result;
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

let chartReady = false;
function ensureChart() {
  if (chartReady || typeof window.TradeIQChart === "undefined" || typeof LightweightCharts === "undefined") return chartReady;
  window.TradeIQChart.init($("chart"));
  chartReady = true;
  return true;
}

function drawChart() {
  if (!ensureChart()) return;
  const aggregated = aggregateCandles(state.baseCandles, state.timeframe);
  if (aggregated.length < 2) return;
  window.TradeIQChart.setCandles(aggregated);
  if (state.setup) window.TradeIQChart.renderOverlays(state.setup, state.overlays);
}

// Called on every websocket tick: update just the last bar + overlays,
// without resetting the user's zoom/pan.
function updateChartLive() {
  if (!ensureChart()) return;
  const aggregated = aggregateCandles(state.baseCandles, state.timeframe);
  if (!aggregated.length) return;
  window.TradeIQChart.updateLast(aggregated[aggregated.length - 1]);
  if (state.setup) window.TradeIQChart.renderOverlays(state.setup, state.overlays);
}

function refreshOverlays() {
  if (chartReady && state.setup) window.TradeIQChart.renderOverlays(state.setup, state.overlays);
}

async function initialLoad() {
  try {
    const [health, snapshot, dashboard] = await Promise.all([
      fetch("/api/health").then((response) => response.ok ? response.json() : Promise.reject(new Error("Health request failed"))),
      fetch("/api/market/snapshot?timeframe=1&limit=1400").then((response) => response.json()),
      fetch("/api/dashboard").then((response) => response.json()),
    ]);
    state.baseCandles = snapshot.candles;
    state.dataMode = health.mode.toUpperCase();
    renderAll(dashboard.setup, dashboard.meta);
    renderHeader(snapshot);
    evaluateHealth();
    $("chartCaption").textContent = `NASDAQ 100 E-mini · 5m · ${state.dataMode}`;
    connectWebSocket();
  } catch (error) {
    console.error(error); setHealth("error", "NO DATA");
  }
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/market`);
  socket.onopen = () => setConnection(true);
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    const candle = data.candle;
    const last = state.baseCandles.at(-1);
    if (last && new Date(last.time).getTime() === new Date(candle.time).getTime()) state.baseCandles[state.baseCandles.length - 1] = candle;
    else state.baseCandles.push(candle);
    if (state.baseCandles.length > 2400) state.baseCandles.shift();
    renderAll(data.setup, data.meta, true);
    evaluateHealth();
  };
  socket.onerror = () => socket.close();
  socket.onclose = () => { setHealth("error", "RECONNECTING"); setTimeout(connectWebSocket, 2000); };
}

function getNewYorkParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit", weekday: "short",
  }).formatToParts(date);
  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}
function tick() {
  const parts = getNewYorkParts();
  $("clock").textContent = `${parts.hour}:${parts.minute}:${parts.second} ET`;

  // Seconds until the next CME Globex state change (open<->close).
  // Globex: Sun 18:00 ET open → Fri 17:00 ET close, daily halt 17:00–18:00.
  const now = new Date();
  const etNow = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const status = marketStatus();

  let target = new Date(etNow);
  let label;
  if (status.open) {
    // Next close is today at 17:00 ET (Mon–Fri).
    target.setHours(17, 0, 0, 0);
    if (target <= etNow) target.setDate(target.getDate() + 1);
    label = "MARKET CLOSES IN";
  } else {
    // Next open: today 18:00 ET, unless we're past it or it's the weekend,
    // in which case roll forward to the next valid open (skip Fri/Sat night).
    target.setHours(18, 0, 0, 0);
    while (target <= etNow || target.getDay() === 6 || (target.getDay() === 5 && target.getHours() >= 17)) {
      target.setDate(target.getDate() + 1);
      target.setHours(18, 0, 0, 0);
    }
    label = "MARKET OPENS IN";
  }

  let remaining = Math.max(0, Math.floor((target - etNow) / 1000));
  const days = Math.floor(remaining / 86400); remaining %= 86400;
  const hours = String(Math.floor(remaining / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((remaining % 3600) / 60)).padStart(2, "0");
  const secs = String(remaining % 60).padStart(2, "0");

  const timer = $("sessionTimer");
  timer.textContent = days > 0 ? `${days}d ${hours}:${minutes}:${secs}` : `${hours}:${minutes}:${secs}`;
  timer.className = status.open ? "clock g" : "clock r";
  $("sessionState").textContent = label;

  // Session box header mirrors the header session name.
  const s = currentSession();
  const hdr = document.querySelector(".session-hours");
  const eyebrow = document.querySelector(".side-card.session .eyebrow, .session .eyebrow");
  if (eyebrow) eyebrow.textContent = status.open ? `Session · ${s.name}` : "CME Globex · Closed";
  if (hdr) hdr.textContent = status.open ? "NQ trading now" : "Reopens Sun 18:00 ET";
}

$("indicatorToggle").addEventListener("click", () => $("indicatorStrip").classList.toggle("hidden"));
$("templateReset").addEventListener("click", () => {
  Object.keys(state.overlays).forEach((key) => { state.overlays[key] = true; });
  document.querySelectorAll(".overlay-btn").forEach((button) => button.classList.add("active"));
  state.timeframe = 5;
  document.querySelectorAll(".tf").forEach((button) => button.classList.toggle("active", Number(button.dataset.tf) === 5));
  $("chartCaption").textContent = `NASDAQ 100 E-mini · 5m · ${state.dataMode || "SIMULATED"}`;
  drawChart();
});
document.querySelectorAll(".overlay-btn").forEach((button) => button.addEventListener("click", () => {
  const name = button.dataset.overlay; state.overlays[name] = !state.overlays[name]; button.classList.toggle("active", state.overlays[name]); drawChart();
}));
document.querySelectorAll(".tf").forEach((button) => button.addEventListener("click", () => {
  state.timeframe = Number(button.dataset.tf);
  document.querySelectorAll(".tf").forEach((item) => item.classList.remove("active")); button.classList.add("active");
  const label = state.timeframe >= 60 ? `${state.timeframe / 60}h` : `${state.timeframe}m`;
  $("chartCaption").textContent = `NASDAQ 100 E-mini · ${label} · ${state.dataMode || "SIMULATED"}`;
  state.hoverIndex = null; $("chartTooltip").style.display = "none"; drawChart();
}));
document.querySelectorAll("#nav a").forEach((item) => item.addEventListener("click", () => {
  document.querySelectorAll("#nav a").forEach((other) => other.classList.remove("active")); item.classList.add("active");
  const label = item.textContent.trim().toLowerCase();
  const chartMode = label === "chart";
  document.body.classList.toggle("chart-mode", chartMode);
  // Let the layout settle, then tell Lightweight Charts to resize + fit.
  setTimeout(() => {
    if (window.TradeIQChart) { window.TradeIQChart.resize(); if (chartMode) window.TradeIQChart.fit(); }
  }, 60);
}));

// ── CME Globex market hours + live session name ──────────────────
// NQ trades Sun 18:00 ET → Fri 17:00 ET, with a daily maintenance halt
// 17:00–18:00 ET. Outside those windows the market is CLOSED.
function marketStatus() {
  const parts = getNewYorkParts(); // {weekday, hour, minute} in ET
  const day = parts.weekday;       // "Sun".."Sat"
  const etHour = Number(parts.hour) + Number(parts.minute) / 60;
  const closedWeekend =
    (day === "Fri" && etHour >= 17) ||
    day === "Sat" ||
    (day === "Sun" && etHour < 18);
  const dailyHalt = day !== "Sat" && day !== "Sun" && etHour >= 17 && etHour < 18;
  const open = !closedWeekend && !dailyHalt;
  return { open, day, etHour };
}

function currentSession() {
  const status = marketStatus();
  if (!status.open) return { name: "Market Closed", color: "#6E7F97", open: false };
  const nowUtc = new Date().getUTCHours() + new Date().getUTCMinutes() / 60;
  const inRange = (start, end) => start < end ? (nowUtc >= start && nowUtc < end) : (nowUtc >= start || nowUtc < end);
  if (inRange(13.5, 20)) return { name: "New York", color: "#26D07C", open: true };
  if (inRange(7, 13.5)) return { name: "London", color: "#48A3FF", open: true };
  if (inRange(0, 7)) return { name: "Asia", color: "#A98BFF", open: true };
  return { name: "Sydney", color: "#F5B93B", open: true };
}

function updateSessionBadge() {
  const s = currentSession();
  const badge = $("sessionBadge");
  const title = $("sessionTitle");
  if (badge) {
    badge.textContent = s.name.toUpperCase();
    badge.style.color = s.color;
    badge.style.borderColor = s.color + "59";
    badge.style.background = s.color + "1f";
  }
  // Header now shows the session itself (title text) instead of "NQ TRADE ENGINE".
  if (title) { title.textContent = s.open ? `${s.name} Session`.toUpperCase() : "MARKET CLOSED"; title.style.color = s.color; }
}
updateSessionBadge();
setInterval(updateSessionBadge, 30000);
// Periodic health re-check catches a frozen tape even if no ticks arrive.
setInterval(() => { if (state.connected) evaluateHealth(); }, 15000);

// Lightweight Charts handles crosshair/tooltip natively — no manual canvas
// mouse tracking needed. Just keep panels responsive on window resize.
window.addEventListener("resize", () => {
  if (window.TradeIQChart) window.TradeIQChart.resize();
  if (state.meta?.performance) drawEquity(state.meta.performance.equity_curve);
});
setInterval(tick, 1000); tick(); initialLoad();
