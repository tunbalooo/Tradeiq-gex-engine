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
  dataSource: "SIMULATED",
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

function setConnection(connected) {
  state.connected = connected;
  $("liveDot").classList.toggle("offline", !connected);
  $("connectionLabel").textContent = connected ? "LIVE" : "RECONNECTING";
  $("connectionLabel").className = connected ? "g" : "r";
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
    { type: "Call Wall", price: gex.call_wall, gex: gex.call_wall_gex, strength: 5, cls: "b" },
    ...gex.levels.slice(0, 6).map((level) => ({ ...level, cls: (level.gex || 0) >= 0 ? "g" : "r" })),
    { type: "Gamma Flip", price: gex.gamma_flip, gex: null, strength: 0, cls: "a" },
    { type: "Put Wall", price: gex.put_wall, gex: gex.put_wall_gex, strength: 5, cls: "r" },
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
  const gaugeColor = setup.actionable ? COLORS.green : confidence >= 55 ? COLORS.amber : COLORS.red;
  $("gaugeArc").style.stroke = gaugeColor;
  $("confidencePct").textContent = `${Math.round(confidence)}%`;
  $("confidencePct").style.color = gaugeColor;

  const activeStates = ["WAITING_FOR_LIMIT", "FILLED", "TP1_HIT"];
  const quality = setup.order_state === "PREVIEW_ONLY" ? "Preview Only" :
    setup.order_state === "WAITING_FOR_LIMIT" ? "Limit Armed" :
    setup.order_state === "FILLED" ? "Position Filled" :
    setup.order_state === "TP1_HIT" ? "TP1 Hit — Running" :
    setup.order_state.replaceAll("_", " ");
  $("probabilityLabel").textContent = quality;
  $("probabilityLabel").style.color = gaugeColor;
  const coreKeys = ["trend_alignment", "gex_alignment", "ote_overlap", "supply_demand", "gex_ote_zone_cluster"];
  const aligned = coreKeys.filter((key) => setup.signals[key]).length;
  $("coreAlignment").textContent = setup.actionable
    ? `${aligned} / ${coreKeys.length} core confluences aligned — actionable`
    : `${aligned} / ${coreKeys.length} core confluences aligned — do not place yet`;

  const label = setup.order_state === "PREVIEW_ONLY" ? `${setup.direction} PREVIEW` : `${setup.direction} ${setup.order_state.replaceAll("_", " ")}`;
  $("setupLabel").textContent = label;
  $("setupLabel").className = `${classForDirection(setup.direction)} mono setup-side-label`;
  $("setupDirection").textContent = `${setup.direction} ${setup.direction === "LONG" ? "↑" : setup.direction === "SHORT" ? "↓" : ""}`;
  $("setupDirection").className = `v ${classForDirection(setup.direction)}`;
  $("entryLabel").textContent = setup.order_state === "PREVIEW_ONLY" ? "Preview Limit" : setup.order_state === "WAITING_FOR_LIMIT" ? "Armed Limit" : "Filled Entry";
  $("setupEntry").textContent = fmt(setup.entry);
  $("setupStop").textContent = fmt(setup.stop_loss);
  $("setupTp1").textContent = fmt(setup.take_profit_1) + (setup.tp1_r ? ` (${Number(setup.tp1_r).toFixed(1)}R)` : "");
  $("setupTp2").textContent = fmt(setup.take_profit_2) + (setup.tp2_r ? ` (${Number(setup.tp2_r).toFixed(1)}R)` : "");
  $("setupTp1Source").textContent = setup.target_sources?.tp1 || "—";
  $("setupTp2Source").textContent = setup.target_sources?.tp2 || "—";
  $("setupRr").textContent = setup.risk_reward ? `1 : ${Number(setup.risk_reward).toFixed(1)}` : "—";
  const statusText = setup.order_state === "PREVIEW_ONLY" ? "Not Ready To Place" : setup.status.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (x) => x.toUpperCase());
  $("setupStatus").textContent = statusText;
  $("setupStatus").className = `v ${setup.actionable || activeStates.includes(setup.order_state) ? "g" : "a"}`;
  $("setupCluster").textContent = setup.cluster_low != null ? `${fmt(setup.cluster_low)}–${fmt(setup.cluster_high)} · ${(setup.cluster_score * 100).toFixed(0)}%` : "No 3-way cluster";
  $("setupCluster").className = `v ${setup.signals.gex_ote_zone_cluster ? "g" : "a"}`;
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
  const sourceEl = $("gexSource");
  if (sourceEl) sourceEl.textContent = gex.source === "databento-native-nq" ? "Databento Native NQ" : gex.source;
  const normalized = 50 + Math.tanh(gex.net_gex / 1e9) * 42;
  $("gexNeedle").style.left = `${Math.max(2, Math.min(98, normalized))}%`;
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
  $("alerts").innerHTML = items.map((item) => `<tr class="alert-row"><td>${item.time}</td><td class="${classes[item.severity] || "b"}">${item.title}</td></tr>
    <tr><td colspan="2" class="m" style="border-top:none;padding-top:0;font-size:11px">${item.detail}</td></tr>`).join("");
}
function renderNews(items = []) {
  $("news").innerHTML = items.map((item) => `<tr><td>${item.time}</td><td>${item.event}</td><td class="${item.impact === "High" ? "r" : item.impact === "Med" ? "a" : "m"}" style="text-align:right">${item.impact}</td></tr>`).join("");
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

function renderAll(setup, meta) {
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
  drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
  renderGexPage(setup);
  renderConfluencePage(setup);
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

function drawChart(canvasId = "chart") {
  const canvas = $(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth; const height = canvas.clientHeight;
  if (!width || !height) return;
  canvas.width = width * dpr; canvas.height = height * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const aggregated = aggregateCandles(state.baseCandles, state.timeframe);
  const visible = aggregated.slice(-120);
  if (visible.length < 2) return;
  const setup = state.setup;
  const pad = { left: 8, right: 84, top: 10, bottom: 24 };
  const chartWidth = width - pad.left - pad.right; const chartHeight = height - pad.top - pad.bottom;
  const values = visible.flatMap((c) => [c.high, c.low]);
  if (setup) {
    if (state.overlays.gex) values.push(setup.gex.call_wall, setup.gex.put_wall, setup.gex.gamma_flip);
    if (state.overlays.fib) values.push(...setup.fib_levels.map((level) => level.price));
    if (state.overlays.zones) setup.zones.forEach((zone) => values.push(zone.low, zone.high));
    if (state.overlays.trade) values.push(setup.entry, setup.stop_loss, setup.take_profit_1, setup.take_profit_2);
    if (state.overlays.vwap) values.push(setup.vwap, setup.standard_deviation_low, setup.standard_deviation_high);
  }
  const validValues = values.filter((value) => Number.isFinite(Number(value))).map(Number);
  let min = Math.min(...validValues); let max = Math.max(...validValues);
  const margin = Math.max((max - min) * 0.06, 4); min -= margin; max += margin;
  const yOf = (price) => pad.top + (max - price) / (max - min || 1) * chartHeight;
  const step = chartWidth / visible.length;
  const xOf = (index) => pad.left + index * step + step / 2;

  ctx.font = `10px ${getComputedStyle(document.body).getPropertyValue("--mono")}`;
  ctx.textBaseline = "middle";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 6; i += 1) {
    const value = min + (max - min) * i / 6; const y = yOf(value);
    ctx.strokeStyle = "rgba(255,255,255,.035)"; ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + chartWidth, y); ctx.stroke();
    ctx.fillStyle = COLORS.muted; ctx.textAlign = "left"; ctx.fillText(fmt(value, 0), pad.left + chartWidth + 8, y);
  }
  const labelCount = Math.min(8, visible.length);
  for (let i = 0; i < labelCount; i += 1) {
    const index = Math.round(i * (visible.length - 1) / Math.max(1, labelCount - 1));
    ctx.fillStyle = COLORS.muted; ctx.textAlign = "center"; ctx.fillText(timeLabel(visible[index].time), xOf(index), height - 10);
  }

  if (setup && state.overlays.zones) {
    setup.zones.slice(0, 8).forEach((zone) => {
      ctx.fillStyle = zone.kind === "DEMAND" ? "rgba(38,208,124,.085)" : "rgba(255,77,94,.085)";
      const top = yOf(zone.high); const bottom = yOf(zone.low);
      ctx.fillRect(pad.left, top, chartWidth, bottom - top);
      ctx.fillStyle = zone.kind === "DEMAND" ? COLORS.green : COLORS.red; ctx.textAlign = "left";
      ctx.fillText(`${zone.timeframe} ${zone.kind}`, pad.left + 5, top + 8);
    });
  }

  function horizontal(price, label, color, dash = [5, 4], alpha = 0.75, align = "left") {
    if (!Number.isFinite(Number(price))) return;
    const y = yOf(Number(price)); ctx.strokeStyle = color; ctx.globalAlpha = alpha; ctx.setLineDash(dash); ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + chartWidth, y); ctx.stroke();
    ctx.setLineDash([]); ctx.globalAlpha = 1; ctx.fillStyle = color; ctx.textAlign = align;
    ctx.fillText(label, align === "left" ? pad.left + 6 : pad.left + chartWidth - 5, y - 7);
  }

  if (setup && state.overlays.fib) {
    const ote = setup.fib_levels.filter((level) => level.ratio >= 0.618 && level.ratio <= 0.786).map((level) => level.price);
    if (ote.length) {
      const top = yOf(Math.max(...ote)); const bottom = yOf(Math.min(...ote));
      ctx.fillStyle = "rgba(169,139,255,.08)"; ctx.fillRect(pad.left, top, chartWidth, bottom - top);
    }
    setup.fib_levels.forEach((level) => horizontal(level.price, level.ratio.toFixed(3), Math.abs(level.ratio - 0.705) < .002 ? COLORS.amber : "#3A4658", [3, 4], .55, "right"));
  }
  if (setup && state.overlays.gex) {
    horizontal(setup.gex.call_wall, "CALL WALL", COLORS.blue, [7, 4], .9);
    horizontal(setup.gex.gamma_flip, "γ FLIP", COLORS.amber, [7, 4], .9);
    horizontal(setup.gex.put_wall, "PUT WALL", COLORS.red, [7, 4], .9);
  }
  if (setup && state.overlays.vwap) {
    horizontal(setup.vwap, "VWAP", "#E4D06F", [2, 3], .65, "right");
    horizontal(setup.standard_deviation_high, "+1σ", "#5B718C", [2, 4], .5, "right");
    horizontal(setup.standard_deviation_low, "-1σ", "#5B718C", [2, 4], .5, "right");
  }

  if (setup && state.overlays.trade && setup.entry != null) {
    const startX = pad.left + chartWidth * .66; const endX = pad.left + chartWidth;
    const entryY = yOf(setup.entry); const stopY = yOf(setup.stop_loss); const tp2Y = yOf(setup.take_profit_2);
    const preview = setup.order_state === "PREVIEW_ONLY";
    ctx.fillStyle = preview ? "rgba(245,185,59,.025)" : "rgba(38,208,124,.07)";
    ctx.fillRect(startX, Math.min(entryY, tp2Y), endX - startX, Math.abs(tp2Y - entryY));
    ctx.fillStyle = preview ? "rgba(255,77,94,.025)" : "rgba(255,77,94,.08)";
    ctx.fillRect(startX, Math.min(entryY, stopY), endX - startX, Math.abs(stopY - entryY));
    horizontal(setup.entry, preview ? "PREVIEW" : setup.order_state === "FILLED" || setup.order_state === "TP1_HIT" ? "ENTRY" : "LIMIT", COLORS.amber, preview ? [2, 5] : [6, 3], preview ? .55 : .95);
    horizontal(setup.stop_loss, "SL", COLORS.red, preview ? [2, 5] : [6, 3], preview ? .45 : .95);
    horizontal(setup.take_profit_1, `TP1 ${setup.target_sources?.tp1 || ""}`, COLORS.green, preview ? [2, 5] : [6, 3], preview ? .45 : .8);
    horizontal(setup.take_profit_2, `TP2 ${setup.target_sources?.tp2 || ""}`, COLORS.green, preview ? [2, 5] : [6, 3], preview ? .45 : .95);
  }

  if (state.overlays.emas) {
    const drawSeries = (series, color) => {
      ctx.strokeStyle = color; ctx.lineWidth = 1.25; ctx.beginPath();
      series.forEach((value, index) => index ? ctx.lineTo(xOf(index), yOf(value)) : ctx.moveTo(xOf(index), yOf(value)));
      ctx.stroke();
    };
    drawSeries(ema(visible, 55), COLORS.purple); drawSeries(ema(visible, 21), COLORS.blue); drawSeries(ema(visible, 9), COLORS.amber);
  }

  visible.forEach((candle, index) => {
    const x = xOf(index); const up = candle.close >= candle.open; const color = up ? COLORS.green : COLORS.red;
    ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, yOf(candle.high)); ctx.lineTo(x, yOf(candle.low)); ctx.stroke();
    const bodyWidth = Math.max(2, step * .62); const openY = yOf(candle.open); const closeY = yOf(candle.close);
    ctx.fillStyle = color; ctx.fillRect(x - bodyWidth / 2, Math.min(openY, closeY), bodyWidth, Math.max(1, Math.abs(closeY - openY)));
  });

  const last = visible.at(-1); const lastY = yOf(last.close);
  ctx.strokeStyle = last.close >= last.open ? COLORS.green : COLORS.red; ctx.globalAlpha = .55; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(pad.left, lastY); ctx.lineTo(pad.left + chartWidth, lastY); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
  ctx.fillStyle = last.close >= last.open ? COLORS.green : COLORS.red; ctx.fillRect(pad.left + chartWidth, lastY - 9, pad.right, 18);
  ctx.fillStyle = "#04140c"; ctx.textAlign = "left"; ctx.font = `600 10px ${getComputedStyle(document.body).getPropertyValue("--mono")}`; ctx.fillText(fmt(last.close), pad.left + chartWidth + 6, lastY);

  if (state.hoverIndex != null && state.hoverIndex >= 0 && state.hoverIndex < visible.length) {
    const x = xOf(state.hoverIndex); const candle = visible[state.hoverIndex]; const y = yOf(candle.close);
    ctx.strokeStyle = "rgba(216,226,240,.28)"; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, pad.top + chartHeight); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + chartWidth, y); ctx.stroke(); ctx.setLineDash([]);
  }
  if (canvasId === "chart") state.chartMeta = { visible, pad, chartWidth, chartHeight, step, xOf, yOf };
}

async function initialLoad() {
  try {
    const [health, snapshot, dashboard] = await Promise.all([
      fetch("/api/health").then((response) => response.ok ? response.json() : Promise.reject(new Error("Health request failed"))),
      fetch("/api/market/snapshot?timeframe=1&limit=1400").then((response) => response.json()),
      fetch("/api/dashboard").then((response) => response.json()),
    ]);
    state.baseCandles = snapshot.candles;
    state.dataSource = health.data_source === "databento" ? "DATABENTO LIVE" : health.mode.toUpperCase();
    $("modeLabel").textContent = state.dataSource;
    renderAll(dashboard.setup, dashboard.meta);
    $("chartCaption").textContent = `NASDAQ 100 E-mini · 5m · ${state.dataSource}`;
    renderHeader(snapshot);
    setConnection(true);
    connectWebSocket();
  } catch (error) {
    console.error(error); setConnection(false); $("modeLabel").textContent = "ERROR";
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
    renderAll(data.setup, data.meta);
  };
  socket.onerror = () => socket.close();
  socket.onclose = () => { setConnection(false); setTimeout(connectWebSocket, 2000); };
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
  const seconds = Number(parts.hour) * 3600 + Number(parts.minute) * 60 + Number(parts.second);
  const open = 9 * 3600 + 30 * 60; const close = 16 * 3600;
  let remaining; let label;
  if (["Sat", "Sun"].includes(parts.weekday)) { remaining = 0; label = "WEEKEND CLOSED"; }
  else if (seconds < open) { remaining = open - seconds; label = "UNTIL RTH OPEN"; }
  else if (seconds < close) { remaining = close - seconds; label = "UNTIL RTH CLOSE"; }
  else { remaining = 0; label = "RTH CLOSED"; }
  const hours = String(Math.floor(remaining / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((remaining % 3600) / 60)).padStart(2, "0");
  const secs = String(remaining % 60).padStart(2, "0");
  $("sessionTimer").textContent = `${hours}:${minutes}:${secs}`;
  $("sessionState").textContent = label;
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
function setPage(name) {
  document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${name}`));
  document.querySelectorAll("#nav button[data-page]").forEach((button) => button.classList.toggle("active", button.dataset.page === name));
  const titles = { dashboard:"NQ TRADE ENGINE", chart:"ADVANCED NQ CHART", gex:"GEX ANALYSIS", confluence:"CONFLUENCE ENGINE", setups:"TRADE SETUPS", alerts:"ALERT CENTER", positions:"POSITIONS", backtest:"BACKTEST LAB", settings:"SETTINGS" };
  $("pageTitle").textContent = titles[name] || "NQ TRADE ENGINE";
  if (name === "chart") setTimeout(() => drawChart("chartLarge"), 30);
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
function renderGexPage(setup) {
  if (!setup || !$("gexProfile")) return;
  const g = setup.gex;
  $("gexProfile").innerHTML = `<div class="page-stats">${[
    ["Regime",g.regime],["Net GEX",fmtGex(g.net_gex)],["Gamma flip",fmt(g.gamma_flip)],["Call wall",fmt(g.call_wall)],["Put wall",fmt(g.put_wall)]
  ].map(([label,value]) => `<div class="page-stat"><b>${value}</b><small>${label}</small></div>`).join("")}</div><p class="note">Native NQ options data when Databento is available. Dealer-side sign remains an estimate.</p>`;
  const levels = [
    {type:"CALL WALL",price:g.call_wall,gex:g.call_wall_gex,strength:5},
    ...(g.levels || []).slice(0,12),
    {type:"GAMMA FLIP",price:g.gamma_flip,gex:null,strength:0},
    {type:"PUT WALL",price:g.put_wall,gex:g.put_wall_gex,strength:5},
  ];
  $("gexPageTable").innerHTML = levels.map((level) => `<tr><td class="${Number(level.gex||0)>=0?'g':'r'}">${level.type || 'LEVEL'}</td><td>${fmt(level.price)}</td><td>${level.gex == null?'—':fmtGex(level.gex)}</td><td class="a">${level.strength?stars(level.strength):'—'}</td></tr>`).join("");
}
function renderConfluencePage(setup) {
  if (!setup || !$("confluencePage")) return;
  renderScorePage("confluencePage", setup.confidence_components, setup.confidence_maximums);
  $("clusterCard").innerHTML = `<div class="cluster-box page-kv">${pageRow("Cluster score",`${Math.round(Number(setup.cluster_score||0)*100)}%`,setup.cluster_score>=.65?'g':'a')}${pageRow("Cluster range",setup.cluster_low!=null?`${fmt(setup.cluster_low)}–${fmt(setup.cluster_high)}`:'—')}${pageRow("GEX level",fmt(setup.cluster_gex_level))}${pageRow("GEX type",setup.cluster_gex_type||'—')}${pageRow("Zone timeframe",setup.selected_zone_timeframe||'—')}${pageRow("Ordered sequence",setup.signals?.ordered_sequence?'Confirmed':'Not confirmed',setup.signals?.ordered_sequence?'g':'a')}</div>`;
  $("rationale").innerHTML = (setup.rationale || []).map((reason) => `<div class="rationale-item">✓ ${reason}</div>`).join("") || '<p class="note">No active rationale yet.</p>';
}
async function loadSetups() {
  try {
    const rows = await fetch("/api/setups/history").then((response) => response.json());
    $("setupsTable").innerHTML = rows.length ? rows.map((item) => `<tr><td>${new Date(item.updated_at).toLocaleString()}</td><td class="${classForDirection(item.direction)}">${item.direction}</td><td>${fmt(item.confidence,0)}</td><td>${fmt(item.entry)}</td><td>${fmt(item.stop_loss)}</td><td>${fmt(item.take_profit_1)}</td><td>${fmt(item.take_profit_2)}</td><td>${item.order_state}</td><td>${item.result_r ?? '—'}</td></tr>`).join("") : '<tr><td colspan="9" class="m">No persisted setups yet.</td></tr>';
  } catch (error) { toast("Could not load setup history"); }
}
async function loadAlertsPage() {
  try {
    const rows = await fetch("/api/alerts").then((response) => response.json());
    $("alertsPage").innerHTML = rows.length ? rows.map((item) => `<div class="alert-card ${item.severity}"><b>${item.title}</b><small>${item.time} · ${item.detail}</small></div>`).join("") : '<p class="note">No alerts logged yet.</p>';
  } catch (error) { toast("Could not load alerts"); }
}
async function loadPositions() {
  try {
    const rows = await fetch("/api/positions").then((response) => response.json());
    $("positionsPage").innerHTML = rows.length ? rows.map((item) => `<div class="cluster-box page-kv">${pageRow("Symbol",item.symbol)}${pageRow("Direction",item.direction,classForDirection(item.direction))}${pageRow("Entry",fmt(item.entry))}${pageRow("Stop",fmt(item.stop_loss),'r')}${pageRow("TP1",fmt(item.take_profit_1),'g')}${pageRow("TP2",fmt(item.take_profit_2),'g')}${pageRow("State",item.state,'a')}</div>`).join("") : '<p class="note">No active engine-tracked position.</p>';
  } catch (error) { toast("Could not load positions"); }
}
async function loadSettings() {
  try {
    const settings = await fetch("/api/settings").then((response) => response.json());
    $("settingsPage").innerHTML = Object.entries(settings).map(([key,value]) => pageRow(key.replaceAll("_"," "),String(value))).join("");
  } catch (error) { toast("Could not load settings"); }
}
function adminHeaders() { return {"Content-Type":"application/json","X-Admin-Token":$("adminToken")?.value || ""}; }
async function refreshGexCache() {
  const response = await fetch("/api/gex/refresh",{method:"POST",headers:adminHeaders()});
  toast(response.ok ? "GEX refresh started" : "Admin token required");
}

$("indicatorToggle").addEventListener("click", () => $("indicatorStrip").classList.toggle("hidden"));
$("templateReset").addEventListener("click", () => {
  Object.keys(state.overlays).forEach((key) => { state.overlays[key] = true; });
  document.querySelectorAll(".overlay-btn").forEach((button) => button.classList.add("active"));
  state.timeframe = 5;
  document.querySelectorAll(".tf").forEach((button) => button.classList.toggle("active", Number(button.dataset.tf) === 5));
  $("chartCaption").textContent = `NASDAQ 100 E-mini · 5m · ${state.dataSource}`;
  drawChart();
});
document.querySelectorAll(".overlay-btn").forEach((button) => button.addEventListener("click", () => {
  const name = button.dataset.overlay; state.overlays[name] = !state.overlays[name];
  document.querySelectorAll(`.overlay-btn[data-overlay="${name}"]`).forEach((item) => item.classList.toggle("active", state.overlays[name]));
  drawChart(); if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
}));
document.querySelectorAll(".tf").forEach((button) => button.addEventListener("click", () => {
  state.timeframe = Number(button.dataset.tf);
  document.querySelectorAll(".tf").forEach((item) => item.classList.toggle("active", Number(item.dataset.tf) === state.timeframe));
  const label = state.timeframe >= 60 ? `${state.timeframe / 60}h` : `${state.timeframe}m`;
  $("chartCaption").textContent = `NASDAQ 100 E-mini · ${label} · ${state.dataSource}`;
  state.hoverIndex = null; $("chartTooltip").style.display = "none"; drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
}));
document.querySelectorAll("#nav button[data-page]").forEach((item) => item.addEventListener("click", () => setPage(item.dataset.page)));

$("chart").addEventListener("mousemove", (event) => {
  if (!state.chartMeta) return;
  const rect = $("chart").getBoundingClientRect(); const x = event.clientX - rect.left;
  const { visible, pad, chartWidth, step } = state.chartMeta;
  if (x < pad.left || x > pad.left + chartWidth) { state.hoverIndex = null; $("chartTooltip").style.display = "none"; drawChart(); return; }
  state.hoverIndex = Math.max(0, Math.min(visible.length - 1, Math.floor((x - pad.left) / step)));
  const candle = visible[state.hoverIndex];
  const tooltip = $("chartTooltip");
  tooltip.innerHTML = `${new Date(candle.time).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}<br>O ${fmt(candle.open)} &nbsp; H ${fmt(candle.high)}<br>L ${fmt(candle.low)} &nbsp; C ${fmt(candle.close)}<br>V ${fmt(candle.volume, 0)}`;
  tooltip.style.display = "block";
  tooltip.style.left = `${Math.min(rect.width - 165, x + 12)}px`;
  tooltip.style.top = `${Math.max(8, Math.min(rect.height - 75, event.clientY - rect.top + 12))}px`;
  drawChart();
});
$("chart").addEventListener("mouseleave", () => { state.hoverIndex = null; $("chartTooltip").style.display = "none"; drawChart(); });
window.addEventListener("resize", () => { drawChart(); if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge"); if (state.meta?.performance) drawEquity(state.meta.performance.equity_curve); });

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
    $("backtestTable").innerHTML = (result.rows || []).map((item) => `<tr><td>${new Date(item.time).toLocaleString()}</td><td class="${classForDirection(item.direction)}">${item.direction}</td><td>${fmt(item.entry)}</td><td>${fmt(item.stop)}</td><td>${fmt(item.target)}</td><td class="${item.result_r>0?'g':item.result_r<0?'r':'a'}">${item.result_r}R</td></tr>`).join("");
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
setInterval(tick, 1000); tick(); initialLoad();
