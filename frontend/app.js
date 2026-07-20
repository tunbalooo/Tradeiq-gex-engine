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
const ACTIVE_TRADE_STATES = new Set(["WAITING_FOR_LIMIT", "FILLED", "TP1_HIT"]);

function hasWatchingPlan(setup) {
  return Boolean(
    setup
    && setup.order_state === "WATCHING"
    && ["LONG", "SHORT"].includes(setup.direction)
    && Number.isFinite(Number(setup.entry))
  );
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
  overlays: { emas: true, gex: true, fib: true, zones: true, trade: true, vwap: true },
  claude: { enabled: false, auto: true, busy: false, source: null, text: "", model: "—", lastStartedAt: 0 },
  mobilePane: localStorage.getItem("tradeiq-mobile-pane") || "chart",
  mobileNewsTab: localStorage.getItem("tradeiq-mobile-news-tab") || "calendar",
  deferredInstallPrompt: null,
};

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
  if ($("chartBrandTitle")) $("chartBrandTitle").innerHTML = `Trade<span>IQ</span> · ${escapeHtml(instrument.symbol)}`;
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
  const date = new Date(value);
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" });
}
function newsDateParts(item = {}) {
  const raw = item.published_at || item.datetime || item.date || null;
  const date = raw ? new Date(raw) : null;
  if (!date || Number.isNaN(date.getTime())) {
    return { day: "—", date: "Date unavailable", time: String(item.time || "—"), full: String(item.time || "—") };
  }
  const day = date.toLocaleDateString("en-US", { weekday: "short", timeZone: "America/New_York" });
  const calendarDate = date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: date.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined, timeZone: "America/New_York" });
  const clock = date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "America/New_York" });
  return { day, date: calendarDate, time: `${clock} ET`, full: `${day}, ${calendarDate} · ${clock} ET` };
}
function calendarDateParts(item = {}) {
  const raw = item.scheduled_at || item.time || null;
  const date = raw ? new Date(raw) : null;
  if (!date || Number.isNaN(date.getTime())) {
    return { day: "—", date: "Date unavailable", time: "—", full: "Scheduled time unavailable" };
  }
  const day = date.toLocaleDateString("en-US", { weekday: "short", timeZone: "America/New_York" });
  const calendarDate = date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "America/New_York" });
  const clock = date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "America/New_York" });
  return { day, date: calendarDate, time: `${clock} ET`, full: `${day}, ${calendarDate} · ${clock} ET` };
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
  const gex = state.setup?.gex;
  if (!gex) return;
  drawGexStrikeChart($("gexStrikeChart"), gex, false);
  drawGexStrikeChart($("mobileGexStrikeChart"), gex, true);
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
  const headingPattern = /^(BIAS|STATUS|CONFIRMED|MISSING|WHAT I SEE|WHAT IS MISSING|RISK|ACTION):\s*(.*)$/i;
  text.split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) return;
    const match = line.match(headingPattern);
    if (match) {
      const rawHeading = match[1].toUpperCase();
      const heading = rawHeading === "WHAT I SEE" ? "CONFIRMED" : rawHeading === "WHAT IS MISSING" ? "MISSING" : rawHeading;
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
      $("claudeFoot").textContent = status.cached_at ? `Last generated ${new Date(status.cached_at).toLocaleTimeString()}` : "Ready. Analysis is cached to control API cost.";
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
}

function startClaudeAnalysis(force = false) {
  if (!state.claude.enabled || state.claude.busy || !$("claudeAnalysis")) return;
  // Automatic analysis waits for real/cached Databento history. The manual
  // Analyze Now button can still be used during a visible syncing preview.
  if (!force && state.marketWarming) return;
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
      ? `Generated ${new Date(payload.generated_at).toLocaleTimeString()} · read-only analysis`
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

function maybeRunClaudeOnStateChange(previousSetup, nextSetup) {
  if (state.currentPage !== "chart" || state.marketWarming || !state.claude.enabled || !state.claude.auto || !previousSetup || !nextSetup) return;
  const importantChange = previousSetup.order_state !== nextSetup.order_state
    || previousSetup.direction !== nextSetup.direction
    || Boolean(previousSetup.actionable) !== Boolean(nextSetup.actionable);
  if (importantChange && Date.now() - state.claude.lastStartedAt > 30000) startClaudeAnalysis(false);
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

function previewExplanation(setup, { syncing = false, marketClosed = false } = {}) {
  if (hasWatchingPlan(setup)) return `Watching ${setup.direction.toLowerCase()} at ${fmt(setup.entry)}. The watch level is fixed; no order is armed. SL, TP and the risk box appear only after confirmation.`;
  if (syncing) return "Temporary levels from local placeholder data while Databento history syncs. Do not trade this preview.";
  if (marketClosed) return "Watch-only candidate from the latest closed data. It can change or disappear when live trading resumes.";
  if (!setup.entry_valid) return "Candidate only: the proposed level is not currently a valid resting limit.";
  if (!setup.actionable) return "Candidate only: one or more mandatory confirmations are still missing. It is not an armed order.";
  return "Candidate levels only. TradeIQ has not armed an order.";
}

function renderTradeSetup(setup) {
  const confidence = Math.max(0, Math.min(100, Number(setup.confidence)));
  const circumference = 307.9;
  $("gaugeArc").style.strokeDashoffset = String(circumference * (1 - confidence / 100));
  const gaugeColor = setup.actionable ? COLORS.green : confidence >= 55 ? COLORS.amber : COLORS.red;
  $("gaugeArc").style.stroke = gaugeColor;
  $("confidencePct").textContent = `${Math.round(confidence)}%`;
  $("confidencePct").style.color = gaugeColor;

  const activeStates = [...ACTIVE_TRADE_STATES];
  const watchingPlan = hasWatchingPlan(setup);
  const lockedPlan = hasLockedTradePlan(setup);
  const syncing = state.marketWarming || setup.status === "DATA_SYNCING";
  const marketClosed = state.session && !state.session.is_open;
  const quality = watchingPlan ? `Watching ${setup.direction.charAt(0)}${setup.direction.slice(1).toLowerCase()}` :
    setup.order_state === "PREVIEW_ONLY" ? (setup.status === "WATCH_EXPIRED" ? "Watch Expired" : "Scanning") :
    setup.order_state === "WAITING_FOR_LIMIT" ? "Limit Armed" :
    setup.order_state === "FILLED" ? "Position Filled" :
    setup.order_state === "TP1_HIT" ? "TP1 Hit — Running" :
    setup.order_state.replaceAll("_", " ");
  $("probabilityLabel").textContent = syncing ? "Data Syncing" : marketClosed ? "Market Closed" : quality;
  $("probabilityLabel").style.color = gaugeColor;
  const coreKeys = ["trend_alignment", "gex_alignment", "ote_overlap", "supply_demand", "gex_ote_zone_cluster"];
  const aligned = coreKeys.filter((key) => setup.signals[key]).length;
  $("coreAlignment").textContent = syncing
    ? `${aligned} / ${coreKeys.length} core confluences aligned — score preserved, no order while history syncs`
    : marketClosed
    ? `${aligned} / ${coreKeys.length} core confluences aligned — score preserved, no new order`
    : setup.actionable
      ? `${aligned} / ${coreKeys.length} core confluences aligned — actionable`
      : watchingPlan
        ? `${aligned} / ${coreKeys.length} aligned — watching for final confirmation`
        : `${aligned} / ${coreKeys.length} core confluences aligned — scanning`;

  const label = watchingPlan
    ? `WATCHING ${setup.direction} @ ${fmt(setup.entry)}`
    : setup.order_state === "PREVIEW_ONLY" ? (setup.status === "WATCH_EXPIRED" ? "WATCH EXPIRED" : "SCANNING") : `${setup.direction} ${setup.order_state.replaceAll("_", " ")}`;
  $("setupLabel").textContent = syncing ? "DATA SYNCING" : marketClosed ? "MARKET CLOSED" : label;
  $("setupLabel").className = `${syncing || marketClosed ? "a" : classForDirection(setup.direction)} mono setup-side-label`;
  $("setupDirection").textContent = `${setup.direction} ${setup.direction === "LONG" ? "↑" : setup.direction === "SHORT" ? "↓" : ""}`;
  $("setupDirection").className = `v ${classForDirection(setup.direction)}`;
  $("entryLabel").textContent = watchingPlan ? "Watching Entry" : lockedPlan ? (setup.order_state === "WAITING_FOR_LIMIT" ? "Locked Limit Entry" : "Filled Entry") : "Entry";
  $("setupEntry").textContent = watchingPlan || lockedPlan ? fmt(setup.entry) : "—";
  $("setupStop").textContent = lockedPlan ? fmt(setup.stop_loss) : "—";
  $("setupTp1").textContent = lockedPlan ? fmt(setup.take_profit_1) + (setup.tp1_r ? ` (${Number(setup.tp1_r).toFixed(1)}R)` : "") : "—";
  $("setupTp2").textContent = lockedPlan ? fmt(setup.take_profit_2) + (setup.tp2_r ? ` (${Number(setup.tp2_r).toFixed(1)}R)` : "") : "—";
  $("setupTp1Source").textContent = lockedPlan ? (setup.target_sources?.tp1 || "—") : "—";
  $("setupTp2Source").textContent = lockedPlan ? (setup.target_sources?.tp2 || "—") : "—";
  $("setupRr").textContent = lockedPlan && setup.risk_reward ? `1 : ${Number(setup.risk_reward).toFixed(1)}` : "—";
  const statusText = syncing ? "Data Syncing" : marketClosed ? "Market Closed" : watchingPlan ? `Watching ${setup.direction.toLowerCase()} at ${fmt(setup.entry)}` : setup.order_state === "PREVIEW_ONLY" ? (setup.status === "WATCH_EXPIRED" ? "Watch expired — waiting for a new candidate" : "Scanning — no setup") : setup.status.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (x) => x.toUpperCase());
  $("setupStatus").textContent = statusText;
  $("setupStatus").className = `v ${setup.actionable || activeStates.includes(setup.order_state) ? "g" : "a"}`;
  $("setupCluster").textContent = setup.cluster_low != null ? `${fmt(setup.cluster_low)}–${fmt(setup.cluster_high)} · ${(setup.cluster_score * 100).toFixed(0)}%` : "No 3-way cluster";
  $("setupCluster").className = `v ${setup.signals.gex_ote_zone_cluster ? "g" : "a"}`;
  $("setupSession").textContent = state.session?.display_name || "—";
  $("setupSession").className = `v ${marketClosed ? "r" : "g"}`;
  $("validLabel").textContent = syncing ? "History" : marketClosed ? "Opens In" : watchingPlan ? "Watch Expires" : "Valid Until";
  $("setupValid").textContent = syncing ? "SYNCING" : marketClosed ? remainingText(state.session?.next_open_at) : new Date(watchingPlan ? (setup.watch_expires_at || setup.valid_until) : setup.valid_until).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "America/New_York" });
  renderChartTradeSetup(setup, {
    confidence,
    gaugeColor,
    marketClosed,
    syncing,
    quality,
    aligned,
    coreCount: coreKeys.length,
    label,
    statusText,
    activeStates,
    watchingPlan,
    lockedPlan,
  });
}

function renderChartTradeSetup(setup, context) {
  if (!$("chartSetupPanel")) return;
  const { confidence, gaugeColor, marketClosed, syncing, quality, aligned, coreCount, label, statusText, activeStates, watchingPlan, lockedPlan } = context;
  const ring = $("chartConfidenceRing");
  ring.style.setProperty("--chart-confidence", `${confidence * 3.6}deg`);
  ring.style.setProperty("--chart-confidence-color", gaugeColor);
  $("chartConfidencePct").textContent = `${Math.round(confidence)}%`;
  $("chartConfidencePct").style.color = gaugeColor;
  $("chartProbabilityLabel").textContent = syncing ? "Data Syncing" : marketClosed ? "Market Closed" : quality;
  $("chartProbabilityLabel").style.color = gaugeColor;
  $("chartCoreAlignment").textContent = syncing
    ? `${aligned} / ${coreCount} aligned — score preserved while history syncs`
    : marketClosed
    ? `${aligned} / ${coreCount} core confluences aligned — score preserved`
    : setup.actionable
      ? `${aligned} / ${coreCount} aligned — actionable`
      : watchingPlan
        ? `${aligned} / ${coreCount} aligned — watching for final confirmation`
        : `${aligned} / ${coreCount} aligned — scanning`;

  $("chartSetupLabel").textContent = syncing ? "DATA SYNCING" : marketClosed ? "MARKET CLOSED" : label;
  $("chartSetupLabel").className = `${syncing ? "a" : marketClosed ? "r" : classForDirection(setup.direction)} mono`;
  $("chartSetupDirection").textContent = `${setup.direction} ${setup.direction === "LONG" ? "↑" : setup.direction === "SHORT" ? "↓" : ""}`;
  $("chartSetupDirection").className = classForDirection(setup.direction);
  $("chartEntryLabel").textContent = watchingPlan ? "Watching Entry" : lockedPlan ? (setup.order_state === "WAITING_FOR_LIMIT" ? "Locked Limit Entry" : "Filled Entry") : "Entry";
  $("chartSetupEntry").textContent = watchingPlan || lockedPlan ? fmt(setup.entry) : "—";
  $("chartSetupStop").textContent = lockedPlan ? fmt(setup.stop_loss) : "—";
  $("chartSetupTp1").textContent = lockedPlan ? fmt(setup.take_profit_1) + (setup.tp1_r ? ` (${Number(setup.tp1_r).toFixed(1)}R)` : "") : "—";
  $("chartSetupTp2").textContent = lockedPlan ? fmt(setup.take_profit_2) + (setup.tp2_r ? ` (${Number(setup.tp2_r).toFixed(1)}R)` : "") : "—";
  $("chartSetupTp1Source").textContent = lockedPlan ? (setup.target_sources?.tp1 || "—") : "—";
  $("chartSetupTp2Source").textContent = lockedPlan ? (setup.target_sources?.tp2 || "—") : "—";
  $("chartSetupRr").textContent = lockedPlan && setup.risk_reward ? `1 : ${Number(setup.risk_reward).toFixed(1)}` : "—";
  $("chartSetupStatus").textContent = statusText;
  $("chartSetupStatus").className = setup.actionable || activeStates.includes(setup.order_state) ? "g" : "a";
  $("chartSetupCluster").textContent = setup.cluster_low != null ? `${fmt(setup.cluster_low)}–${fmt(setup.cluster_high)} · ${(setup.cluster_score * 100).toFixed(0)}%` : "No 3-way cluster";
  $("chartSetupCluster").className = setup.signals.gex_ote_zone_cluster ? "g" : "a";
  $("chartSetupSession").textContent = state.session?.display_name || "—";
  $("chartSetupSession").className = marketClosed ? "r" : "g";
  $("chartValidLabel").textContent = syncing ? "History" : marketClosed ? "Opens In" : watchingPlan ? "Watch Expires" : "Valid Until";
  $("chartSetupValid").textContent = syncing ? "SYNCING" : marketClosed ? remainingText(state.session?.next_open_at) : new Date(watchingPlan ? (setup.watch_expires_at || setup.valid_until) : setup.valid_until).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "America/New_York" });
  const previewNotice = $("chartPreviewNotice");
  if (previewNotice) {
    const informational = setup.order_state === "PREVIEW_ONLY" || watchingPlan;
    previewNotice.hidden = !informational;
    previewNotice.classList.toggle("syncing", Boolean(syncing));
    previewNotice.classList.toggle("closed", Boolean(marketClosed));
    previewNotice.classList.toggle("watching", Boolean(watchingPlan));
    const title = $("chartPreviewTitle");
    if (title) title.textContent = watchingPlan ? `WATCHING ${setup.direction} @ ${fmt(setup.entry)}` : "SCANNING — NO ACTIVE SETUP";
    if (informational && $("chartPreviewReason")) $("chartPreviewReason").textContent = previewExplanation(setup, { syncing, marketClosed });
  }
}
function renderGexSummary(setup) {
  const gex = setup.gex;
  $("gexRegime").textContent = `${gex.regime.charAt(0)}${gex.regime.slice(1).toLowerCase()} Gamma`;
  $("gexRegime").className = `v ${gex.regime === "POSITIVE" ? "g" : gex.regime === "NEGATIVE" ? "r" : "a"}`;
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
      ? "Estimated fallback GEX: use the price levels as context, not as confirmed options positioning. It never changes the confidence score."
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
  $("alerts").innerHTML = items.map((item) => `<tr class="alert-row"><td>${item.time}</td><td class="${classes[item.severity] || "b"}">${item.title}</td></tr>
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
  if (session) renderSession(session);
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
  renderEconomicCalendar(meta.economic_events || [], meta.economic_calendar_status || {});
  renderNews(meta.news);
  renderPerformance(meta.performance);
  drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
  renderGexPage(setup);
  renderConfluencePage(setup);
  maybeRunClaudeOnStateChange(previousSetup, setup);
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

function drawChart(chartId = "chart") {
  const manager = window.TradeIQChartManager;
  if (!manager) return;
  if (chartId === "chartLarge" && $("chartLargeStatus")) $("chartLargeStatus").textContent = chartFeedLabel();
  manager.render(chartId, {
    candles: aggregateCandles(state.baseCandles, state.timeframe),
    setup: state.setup,
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
    const [health, snapshot, dashboard] = await Promise.all([
      fetch("/api/health").then((response) => response.ok ? response.json() : Promise.reject(new Error("Health request failed"))),
      fetch("/api/market/snapshot?timeframe=1&limit=1400").then((response) => response.json()),
      fetch("/api/dashboard").then(async (response) => response.ok ? response.json() : null),
    ]);
    state.baseCandles = snapshot.candles || [];
    applySnapshotMetadata(snapshot);
    const initialMarket = health.market || {};
    state.marketWarming = Boolean(initialMarket.warming || (health.data_source === "databento" && !initialMarket.history_cached) || snapshot.warming);
    state.historyReady = Boolean(snapshot.history_ready ?? initialMarket.history_ready ?? initialMarket.history_cached);
    state.historySource = snapshot.history_source || initialMarket.history_source || state.historySource;
    state.dataQuality = snapshot.data_quality || initialMarket.data_quality || state.dataQuality;
    state.rawSymbol = snapshot.raw_symbol || initialMarket.raw_symbol || null;
    state.dataSource = health.data_source === "databento"
      ? (initialMarket.last_error && !initialMarket.history_cached ? "DATABENTO ERROR" : state.marketWarming ? "DATABENTO SYNC" : "DATABENTO LIVE")
      : health.mode.toUpperCase();
    applyInstrument(snapshot.instrument || health.instrument || health.market?.instrument);
    $("modeLabel").textContent = state.dataSource;
    if (dashboard?.setup && dashboard?.meta) renderAll(dashboard.setup, dashboard.meta, dashboard.session || health.session);
    else renderSyncingState(snapshot, health.session);
    $("chartCaption").textContent = chartFeedLabel();
    renderHeader(snapshot);
    setConnection(true);
    await loadClaudeStatus();
    loadEconomicCalendar();
    connectWebSocket();
  } catch (error) {
    console.error(error); setConnection(false); $("modeLabel").textContent = "ERROR";
  }
}


async function reloadSyncedHistory() {
  try {
    const snapshot = await fetch("/api/market/snapshot?timeframe=1&limit=1400").then((response) => {
      if (!response.ok) throw new Error(`Snapshot refresh failed (${response.status})`);
      return response.json();
    });
    if (snapshot.symbol && snapshot.symbol !== activeSymbol()) return false;
    state.baseCandles = snapshot.candles || [];
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

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/market`);
  state.socket = socket;
  socket.onopen = () => setConnection(true);
  socket.onmessage = async (event) => {
    if (state.switchingSymbol) return;
    const data = JSON.parse(event.data);
    const wasWarming = state.marketWarming;
    state.marketWarming = Boolean(data.market?.warming || (data.market?.data_source === "databento" && !data.market?.history_cached));
    state.historyReady = Boolean(data.market?.history_ready ?? data.market?.history_cached);
    state.historySource = data.market?.history_source || state.historySource;
    state.dataQuality = data.market?.data_quality || state.dataQuality;
    state.rawSymbol = data.market?.raw_symbol || state.rawSymbol;
    if (data.market?.data_source === "databento") {
      state.dataSource = data.market?.last_error && !data.market?.history_cached ? "DATABENTO ERROR" : state.marketWarming ? "DATABENTO SYNC" : "DATABENTO LIVE";
      if ($("modeLabel")) $("modeLabel").textContent = state.dataSource;
    }
    const incomingInstrument = data.market?.instrument;
    if (incomingInstrument && incomingInstrument.symbol !== activeSymbol()) {
      state.baseCandles = [];
      applyInstrument(incomingInstrument);
    }
    const candle = data.candle;
    if (candle) {
      const last = state.baseCandles.at(-1);
      if (last && new Date(last.time).getTime() === new Date(candle.time).getTime()) state.baseCandles[state.baseCandles.length - 1] = candle;
      else state.baseCandles.push(candle);
      if (state.baseCandles.length > 2400) state.baseCandles.shift();
    }
    if (data.setup && data.meta) renderAll(data.setup, data.meta, data.session);
    else renderSyncingState({ price: candle?.close }, data.session);
    if (wasWarming && !state.marketWarming) {
      await reloadSyncedHistory();
      if (state.currentPage === "chart" && state.claude.enabled && state.claude.auto && !state.claude.busy) {
        startClaudeAnalysis(false);
      }
    }
  };
  socket.onerror = () => socket.close();
  socket.onclose = () => {
    if (state.socket === socket) state.socket = null;
    setConnection(false);
    setTimeout(connectWebSocket, 2000);
  };
}

async function switchMarket(symbol) {
  const selector = $("symbolSelect");
  if (!selector || state.switchingSymbol || symbol === activeSymbol()) return;
  state.switchingSymbol = true;
  selector.disabled = true;
  selector.closest(".symbol-selector")?.classList.add("busy");
  stopClaudeStream();
  state.claude.text = "";
  renderClaudeAnalysis("", false);
  setClaudeStatus("WAITING", "cached");
  if ($("claudeFoot")) $("claudeFoot").textContent = `Waiting for ${symbol} market data…`;
  toast(`Switching TradeIQ to ${symbol}…`);
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
    state.dataSource = selected.market?.data_source === "databento"
      ? (selected.market?.last_error && !selected.market?.history_cached ? "DATABENTO ERROR" : state.marketWarming ? "DATABENTO SYNC" : "DATABENTO LIVE")
      : String(selected.market?.mode || "simulated").toUpperCase();
    if ($("modeLabel")) $("modeLabel").textContent = state.dataSource;
    const [snapshot, dashboard] = await Promise.all([
      fetch("/api/market/snapshot?timeframe=1&limit=1400").then((item) => item.json()),
      fetch("/api/dashboard").then(async (item) => item.ok ? item.json() : null),
    ]);
    state.baseCandles = snapshot.candles || [];
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
    await loadClaudeStatus();
    if (!state.marketWarming && state.currentPage === "chart" && state.claude.enabled && state.claude.auto) {
      startClaudeAnalysis(false);
    }
    toast(state.marketWarming ? `${symbol} loaded · Databento history syncing` : `${symbol} market loaded`);
  } catch (error) {
    console.error(error);
    selector.value = activeSymbol();
    toast(error.message || "Could not switch market");
  } finally {
    state.switchingSymbol = false;
    selector.disabled = false;
    selector.closest(".symbol-selector")?.classList.remove("busy");
  }
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
  const titles = { dashboard:dashboardTitle, chart:`ADVANCED ${symbol} CHART`, gex:`${symbol} GEX ANALYSIS`, confluence:`${symbol} CONFLUENCE ENGINE`, setups:`${symbol} TRADE SETUPS`, alerts:"ALERT CENTER", positions:"POSITIONS", backtest:`${symbol} BACKTEST LAB`, settings:"SETTINGS" };
  $("pageTitle").textContent = titles[name] || dashboardTitle;
  syncMobileNavigation();
  if (!runLoaders) return;
  if (name === "chart") setTimeout(() => { drawChart("chartLarge"); if (state.claude.enabled && state.claude.auto && !state.claude.text) startClaudeAnalysis(false); }, 30);
  if (name === "gex") window.setTimeout(refreshGexCharts, 30);
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
  const parentNote = g.is_parent_market ? ` Parent-market levels are applied to the ${activeSymbol()} chart.` : "";
  $("gexProfile").innerHTML = `<div class="page-stats">${[
    ["Regime",g.regime],["Net GEX",fmtGex(g.net_gex)],["Gamma flip",fmt(g.gamma_flip)],
    ["Gamma resistance",fmt(g.gamma_resistance ?? g.call_wall)],
    ["Maximum pain",Number.isFinite(Number(g.max_pain)) ? fmt(g.max_pain) : "Native OI required"],
    ["Put support",fmt(g.gamma_support ?? g.put_wall)]
  ].map(([label,value]) => `<div class="page-stat"><b>${value}</b><small>${label}</small></div>`).join("")}</div><p class="note">GEX source: ${escapeHtml(g.source_label || g.source || "fallback")}.${parentNote} Maximum pain is shown only when open-interest data is available; no level is fabricated.</p>`;
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
  $("chartCaption").textContent = chartFeedLabel();
  drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
  window.TradeIQChartManager?.reset("chart");
  window.TradeIQChartManager?.reset("chartLarge");
});
document.querySelectorAll(".overlay-btn").forEach((button) => button.addEventListener("click", () => {
  const name = button.dataset.overlay; state.overlays[name] = !state.overlays[name];
  document.querySelectorAll(`.overlay-btn[data-overlay="${name}"]`).forEach((item) => item.classList.toggle("active", state.overlays[name]));
  drawChart(); if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
}));
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
if ($("claudeAnalyze")) $("claudeAnalyze").addEventListener("click", () => startClaudeAnalysis(true));
if ($("claudeAuto")) $("claudeAuto").addEventListener("change", (event) => {
  state.claude.auto = Boolean(event.target.checked);
  if (state.claude.auto && state.currentPage === "chart" && state.claude.enabled) startClaudeAnalysis(false);
});
setInterval(() => {
  if (state.currentPage === "chart" && state.claude.enabled && state.claude.auto && !state.claude.busy) startClaudeAnalysis(false);
}, 300000);
setInterval(loadEconomicCalendar, 900000);

setInterval(tick, 1000); tick(); initialLoad();
