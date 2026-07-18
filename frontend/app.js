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
  session: null,
  currentPage: "dashboard",
  hoverIndex: null,
  chartMeta: null,
  overlays: { emas: true, gex: true, fib: true, zones: true, trade: true, vwap: true },
  claude: { enabled: false, auto: true, busy: false, source: null, text: "", model: "—", lastStartedAt: 0 },
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
  const headingPattern = /^(BIAS|STATUS|WHAT I SEE|WHAT IS MISSING|RISK|ACTION):\s*(.*)$/i;
  text.split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) return;
    const match = line.match(headingPattern);
    if (match) {
      current = { heading: match[1].toUpperCase(), lines: [] };
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
    return `<section class="claude-analysis-section"><h4>${escapeHtml(section.heading)}</h4>${prose ? `<p>${prose}</p>` : ""}${bullets.length ? `<ul>${bullets.join("")}</ul>` : ""}</section>`;
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
  $("claudeAnalyze")?.removeAttribute("disabled");
}

function startClaudeAnalysis(force = false) {
  if (!state.claude.enabled || state.claude.busy || !$("claudeAnalysis")) return;
  state.claude.busy = true;
  state.claude.text = "";
  state.claude.lastStartedAt = Date.now();
  $("claudeAnalyze").disabled = true;
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
  if (state.currentPage !== "chart" || !state.claude.enabled || !state.claude.auto || !previousSetup || !nextSetup) return;
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
  if (state.currentPage === "dashboard") $("pageTitle").textContent = open ? session.display_name : "MARKET CLOSED";
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
  const marketClosed = state.session && !state.session.is_open;
  const quality = setup.order_state === "PREVIEW_ONLY" ? "Preview Only" :
    setup.order_state === "WAITING_FOR_LIMIT" ? "Limit Armed" :
    setup.order_state === "FILLED" ? "Position Filled" :
    setup.order_state === "TP1_HIT" ? "TP1 Hit — Running" :
    setup.order_state.replaceAll("_", " ");
  $("probabilityLabel").textContent = marketClosed ? "Market Closed" : quality;
  $("probabilityLabel").style.color = gaugeColor;
  const coreKeys = ["trend_alignment", "gex_alignment", "ote_overlap", "supply_demand", "gex_ote_zone_cluster"];
  const aligned = coreKeys.filter((key) => setup.signals[key]).length;
  $("coreAlignment").textContent = marketClosed
    ? `${aligned} / ${coreKeys.length} core confluences aligned — score preserved, no new order`
    : setup.actionable
      ? `${aligned} / ${coreKeys.length} core confluences aligned — actionable`
      : `${aligned} / ${coreKeys.length} core confluences aligned — do not place yet`;

  const label = setup.order_state === "PREVIEW_ONLY" ? `${setup.direction} PREVIEW` : `${setup.direction} ${setup.order_state.replaceAll("_", " ")}`;
  $("setupLabel").textContent = marketClosed ? "MARKET CLOSED" : label;
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
  const statusText = marketClosed ? "Market Closed" : setup.order_state === "PREVIEW_ONLY" ? "Not Ready To Place" : setup.status.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (x) => x.toUpperCase());
  $("setupStatus").textContent = statusText;
  $("setupStatus").className = `v ${setup.actionable || activeStates.includes(setup.order_state) ? "g" : "a"}`;
  $("setupCluster").textContent = setup.cluster_low != null ? `${fmt(setup.cluster_low)}–${fmt(setup.cluster_high)} · ${(setup.cluster_score * 100).toFixed(0)}%` : "No 3-way cluster";
  $("setupCluster").className = `v ${setup.signals.gex_ote_zone_cluster ? "g" : "a"}`;
  $("setupSession").textContent = state.session?.display_name || "—";
  $("setupSession").className = `v ${marketClosed ? "r" : "g"}`;
  $("validLabel").textContent = marketClosed ? "Opens In" : "Valid Until";
  $("setupValid").textContent = marketClosed ? remainingText(state.session?.next_open_at) : new Date(setup.valid_until).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "America/New_York" });
  renderChartTradeSetup(setup, {
    confidence,
    gaugeColor,
    marketClosed,
    quality,
    aligned,
    coreCount: coreKeys.length,
    label,
    statusText,
    activeStates,
  });
}

function renderChartTradeSetup(setup, context) {
  if (!$("chartSetupPanel")) return;
  const { confidence, gaugeColor, marketClosed, quality, aligned, coreCount, label, statusText, activeStates } = context;
  const ring = $("chartConfidenceRing");
  ring.style.setProperty("--chart-confidence", `${confidence * 3.6}deg`);
  ring.style.setProperty("--chart-confidence-color", gaugeColor);
  $("chartConfidencePct").textContent = `${Math.round(confidence)}%`;
  $("chartConfidencePct").style.color = gaugeColor;
  $("chartProbabilityLabel").textContent = marketClosed ? "Market Closed" : quality;
  $("chartProbabilityLabel").style.color = gaugeColor;
  $("chartCoreAlignment").textContent = marketClosed
    ? `${aligned} / ${coreCount} core confluences aligned — score preserved`
    : setup.actionable
      ? `${aligned} / ${coreCount} aligned — actionable`
      : `${aligned} / ${coreCount} aligned — wait for confirmation`;

  $("chartSetupLabel").textContent = marketClosed ? "MARKET CLOSED" : label;
  $("chartSetupLabel").className = `${marketClosed ? "r" : classForDirection(setup.direction)} mono`;
  $("chartSetupDirection").textContent = `${setup.direction} ${setup.direction === "LONG" ? "↑" : setup.direction === "SHORT" ? "↓" : ""}`;
  $("chartSetupDirection").className = classForDirection(setup.direction);
  $("chartEntryLabel").textContent = setup.order_state === "PREVIEW_ONLY" ? "Preview Limit" : setup.order_state === "WAITING_FOR_LIMIT" ? "Armed Limit" : "Filled Entry";
  $("chartSetupEntry").textContent = fmt(setup.entry);
  $("chartSetupStop").textContent = fmt(setup.stop_loss);
  $("chartSetupTp1").textContent = fmt(setup.take_profit_1) + (setup.tp1_r ? ` (${Number(setup.tp1_r).toFixed(1)}R)` : "");
  $("chartSetupTp2").textContent = fmt(setup.take_profit_2) + (setup.tp2_r ? ` (${Number(setup.tp2_r).toFixed(1)}R)` : "");
  $("chartSetupTp1Source").textContent = setup.target_sources?.tp1 || "—";
  $("chartSetupTp2Source").textContent = setup.target_sources?.tp2 || "—";
  $("chartSetupRr").textContent = setup.risk_reward ? `1 : ${Number(setup.risk_reward).toFixed(1)}` : "—";
  $("chartSetupStatus").textContent = statusText;
  $("chartSetupStatus").className = setup.actionable || activeStates.includes(setup.order_state) ? "g" : "a";
  $("chartSetupCluster").textContent = setup.cluster_low != null ? `${fmt(setup.cluster_low)}–${fmt(setup.cluster_high)} · ${(setup.cluster_score * 100).toFixed(0)}%` : "No 3-way cluster";
  $("chartSetupCluster").className = setup.signals.gex_ote_zone_cluster ? "g" : "a";
  $("chartSetupSession").textContent = state.session?.display_name || "—";
  $("chartSetupSession").className = marketClosed ? "r" : "g";
  $("chartValidLabel").textContent = marketClosed ? "Opens In" : "Valid Until";
  $("chartSetupValid").textContent = marketClosed ? remainingText(state.session?.next_open_at) : new Date(setup.valid_until).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "America/New_York" });
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

function renderAll(setup, meta, session = state.session) {
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
  if (chartId === "chartLarge" && $("chartLargeStatus")) {
    const label = state.timeframe >= 60 ? `${state.timeframe / 60}h` : `${state.timeframe}m`;
    $("chartLargeStatus").textContent = `NASDAQ 100 E-mini · ${label} · ${state.dataSource}`;
  }
  manager.render(chartId, {
    candles: aggregateCandles(state.baseCandles, state.timeframe),
    setup: state.setup,
    overlays: state.overlays,
    timeframe: state.timeframe,
    dataSource: state.dataSource,
  });
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
    renderAll(dashboard.setup, dashboard.meta, dashboard.session || health.session);
    $("chartCaption").textContent = `NASDAQ 100 E-mini · 5m · ${state.dataSource}`;
    renderHeader(snapshot);
    setConnection(true);
    await loadClaudeStatus();
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
    renderAll(data.setup, data.meta, data.session);
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
  if (state.session) {
    $("sessionTimer").textContent = remainingText(state.session.countdown_target);
    if (!state.session.is_open && $("setupValid")) $("setupValid").textContent = remainingText(state.session.next_open_at);
    if (!state.session.is_open && $("chartSetupValid")) $("chartSetupValid").textContent = remainingText(state.session.next_open_at);
  }
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
  state.currentPage = name;
  const dashboardTitle = state.session ? (state.session.is_open ? state.session.display_name : "MARKET CLOSED") : "NQ TRADE ENGINE";
  const titles = { dashboard:dashboardTitle, chart:"ADVANCED NQ CHART", gex:"GEX ANALYSIS", confluence:"CONFLUENCE ENGINE", setups:"TRADE SETUPS", alerts:"ALERT CENTER", positions:"POSITIONS", backtest:"BACKTEST LAB", settings:"SETTINGS" };
  $("pageTitle").textContent = titles[name] || dashboardTitle;
  if (name === "chart") setTimeout(() => { drawChart("chartLarge"); if (state.claude.enabled && state.claude.auto && !state.claude.text) startClaudeAnalysis(false); }, 30);
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
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
  window.TradeIQChartManager?.reset("chart");
  window.TradeIQChartManager?.reset("chartLarge");
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
  state.hoverIndex = null; drawChart();
  if ($("page-chart")?.classList.contains("active")) drawChart("chartLarge");
}));
document.querySelectorAll("#nav button[data-page]").forEach((item) => item.addEventListener("click", () => setPage(item.dataset.page)));

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
if ($("claudeAnalyze")) $("claudeAnalyze").addEventListener("click", () => startClaudeAnalysis(true));
if ($("claudeAuto")) $("claudeAuto").addEventListener("change", (event) => {
  state.claude.auto = Boolean(event.target.checked);
  if (state.claude.auto && state.currentPage === "chart" && state.claude.enabled) startClaudeAnalysis(false);
});
setInterval(() => {
  if (state.currentPage === "chart" && state.claude.enabled && state.claude.auto && !state.claude.busy) startClaudeAnalysis(false);
}, 300000);

setInterval(tick, 1000); tick(); initialLoad();
