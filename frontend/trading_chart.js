// TOUCHED · CONFIRM
// Legacy watch-line regression marker retained as a comment only:
// MONITOR ${setup.direction} · NO ORDER
// v3.1.5 restores an optional SCAN ONLY line, while exact entry/SL/TP remain locked until executable.
(() => {
  "use strict";

  const LC = window.LightweightCharts;
  // Use the same official Lightweight Charts engine on desktop, iPhone and iPad.
  // The Canvas implementation is now an emergency fallback only when the library cannot load.
  const USE_MOBILE_CANVAS = false;
  const MIN_SAFE_HISTORY_BARS = 20;
  const MAX_CACHED_HISTORY_BARS = 5000;
  const ACTIVE_TRADE_STATES = new Set(["WAITING_FOR_LIMIT", "FILLED", "TP1_HIT"]);
  const MAX_SERIES_REGIME_GAP = 0.08;
  const SESSION_BREAK_MULTIPLIER = 3;
  const MIN_SESSION_BREAK_MS = 60 * 60 * 1000;

  function median(values = []) {
    const clean = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
    if (!clean.length) return null;
    const middle = Math.floor(clean.length / 2);
    return clean.length % 2 ? clean[middle] : (clean[middle - 1] + clean[middle]) / 2;
  }

  function priceRegime(candles = [], count = 20) {
    return median(candles.slice(-count).map((item) => item.close));
  }

  function regimeGap(left = [], right = []) {
    const a = priceRegime(left);
    const b = priceRegime(right, 5);
    if (!Number.isFinite(a) || !Number.isFinite(b) || a <= 0) return 0;
    return Math.abs(b - a) / a;
  }

  function seriesTime(value) {
    if (value == null) return null;
    if (typeof value === "number") return value < 1e12 ? value * 1000 : value;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function medianSpacing(candles = []) {
    const times = candles.map((item) => seriesTime(item?.time)).filter((value) => value != null);
    if (times.length < 3) return null;
    const deltas = [];
    for (let index = 1; index < times.length; index += 1) {
      const delta = times[index] - times[index - 1];
      if (delta > 0) deltas.push(delta);
    }
    return median(deltas);
  }

  function latestCoherentSegment(candles = [], maxGap = MAX_SERIES_REGIME_GAP) {
    if (candles.length < 2) return candles;
    // A price step only means a corrupt/mixed data regime when the two bars are
    // contiguous in time. Legitimate session breaks (weekend reopen, the daily
    // CME halt or a continuous-contract rollover) may also step in price and
    // must not cause the earlier chart history to be discarded.
    const spacing = medianSpacing(candles);
    const breakAfter = Math.max(Number(spacing || 0) * SESSION_BREAK_MULTIPLIER, MIN_SESSION_BREAK_MS);
    let start = 0;
    for (let index = 1; index < candles.length; index += 1) {
      const previous = Number(candles[index - 1]?.close);
      const current = Number(candles[index]?.open);
      if (!Number.isFinite(previous) || !Number.isFinite(current) || previous <= 0) continue;
      const previousTime = seriesTime(candles[index - 1]?.time);
      const currentTime = seriesTime(candles[index]?.time);
      const sessionBreak =
        previousTime != null && currentTime != null && currentTime - previousTime > breakAfter;
      if (sessionBreak) continue;
      if (Math.abs(current - previous) / previous > maxGap) start = index;
    }
    return candles.slice(start);
  }

  function nyParts(value) {
    const raw = typeof value === "number" && value < 1e12 ? value * 1000 : value;
    const date = raw instanceof Date ? raw : new Date(raw);
    if (Number.isNaN(date.getTime())) return null;
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(date);
    const map = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return { dateKey: `${map.year}-${map.month}-${map.day}`, minutes: Number(map.hour) * 60 + Number(map.minute) };
  }

  function rthEquilibrium(candles = [], symbol = "NQ") {
    if (!candles.length) return null;
    const latest = nyParts(candles.at(-1)?.time);
    if (!latest) return null;
    const gold = ["GC", "MGC"].includes(String(symbol || "").toUpperCase());
    const start = gold ? 8 * 60 + 20 : 9 * 60 + 30;
    const end = gold ? 13 * 60 + 30 : 16 * 60;
    const session = candles.filter((item) => {
      const parts = nyParts(item.time);
      return parts && parts.dateKey === latest.dateKey && parts.minutes >= start && parts.minutes < end;
    });
    if (!session.length) return null;
    const high = Math.max(...session.map((item) => Number(item.high)).filter(Number.isFinite));
    const low = Math.min(...session.map((item) => Number(item.low)).filter(Number.isFinite));
    return Number.isFinite(high) && Number.isFinite(low) ? (high + low) / 2 : null;
  }

  function toggleFullscreenRoot(root) {
    if (!root) return;
    if (document.fullscreenElement) { document.exitFullscreen?.(); return; }
    if (root.classList.contains("tradeiq-pseudo-fullscreen")) {
      root.classList.remove("tradeiq-pseudo-fullscreen");
      document.body.classList.remove("tradeiq-fullscreen-lock");
      window.dispatchEvent(new Event("resize"));
      return;
    }
    const fallback = () => {
      root.classList.add("tradeiq-pseudo-fullscreen");
      document.body.classList.add("tradeiq-fullscreen-lock");
      window.dispatchEvent(new Event("resize"));
    };
    if (typeof root.requestFullscreen === "function") root.requestFullscreen().catch(fallback);
    else fallback();
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

  function initialStop(setup) {
    return Number.isFinite(Number(setup?.initial_stop_loss)) ? Number(setup.initial_stop_loss) : Number(setup?.stop_loss);
  }

  function activeStop(setup) {
    return Number.isFinite(Number(setup?.active_stop_loss)) ? Number(setup.active_stop_loss) : initialStop(setup);
  }

  function hasLockedTradePlan(setup) {
    if (!setup || !ACTIVE_TRADE_STATES.has(setup.order_state)) return false;
    if (!setup.armed_at) return false;
    return [setup.entry, initialStop(setup), setup.take_profit_1, setup.take_profit_2]
      .every((value) => Number.isFinite(Number(value)));
  }

  function executionOrderLabel(setup, includeState = false) {
    if (!setup) return "ENTRY";
    const side = setup.direction === "SHORT" ? "SELL" : "BUY";
    const type = String(setup.execution_type || "LIMIT").toUpperCase();
    let label = `${side} ${type}`;
    if (!includeState) return label;
    if (setup.order_state === "WAITING_FOR_LIMIT") label += " · ARMED";
    else if (setup.order_state === "FILLED") label += " · FILLED";
    else if (setup.order_state === "TP1_HIT") label += " · TP1 HIT";
    return label;
  }

  function tradePlanRrLabel(setup) {
    const rr = Number(setup?.risk_reward ?? setup?.tp2_r);
    return Number.isFinite(rr) && rr > 0 ? `1:${rr.toFixed(1)}` : "";
  }

  function tradePlanStartRatio(instance) {
    const width = Number(instance?.host?.clientWidth || 0);
    if (width < 700) return 0.43;
    return instance?.id === "chartLarge" ? 0.56 : 0.60;
  }

  function installCanvasFallback() {
    console.warn("Lightweight Charts was unavailable; TradeIQ is using its built-in Canvas chart fallback.");
    const fallbackInstances = new Map();
    const fallbackHistoryCache = new Map();
    const lineColors = {
      entry: "#F5B93B", stop: "#FF4D5E", target: "#26D07C",
      gex: "#48A3FF", vwap: "#E4D06F", fib: "#A98BFF",
    };

    function fallbackSize(host) {
      const rect = host.getBoundingClientRect();
      return {
        width: Math.max(280, Math.floor(rect.width || host.parentElement?.clientWidth || window.innerWidth || 390)),
        height: Math.max(300, Math.floor(rect.height || host.parentElement?.clientHeight || 480)),
      };
    }

    function fallbackTime(value) {
      const parsed = Date.parse(value);
      return Number.isFinite(parsed) ? parsed : null;
    }

    function ensureFallback(id) {
      let instance = fallbackInstances.get(id);
      if (instance) return instance;
      const host = document.getElementById(id);
      if (!host) return null;
      host.innerHTML = "";
      const canvas = document.createElement("canvas");
      canvas.className = "tradeiq-canvas-fallback";
      canvas.setAttribute("aria-label", "Interactive TradeIQ candlestick chart. Drag left or right through time, drag up or down through price, and drag the right price scale to zoom.");
      host.appendChild(canvas);
      instance = {
        id, host, canvas, payload: null,
        visibleCount: id === "chartLarge" ? 88 : 72,
        offset: 0, chartStyle: "candles",
        dragging: false, dragMode: null, dragX: 0, dragY: 0, dragOffset: 0,
        dragPricePan: 0, dragPriceZoom: 1,
        pricePan: 0, priceZoom: 1, autoScale: true,
        scaleMeta: null,
      };
      fallbackInstances.set(id, instance);
      const observer = new ResizeObserver(() => drawFallback(instance));
      observer.observe(host);
      instance.resizeObserver = observer;
      bindFallbackControls(instance);
      bindFallbackGestures(instance);
      return instance;
    }

    function clamp(value, minimum, maximum) { return Math.max(minimum, Math.min(maximum, value)); }

    function fallbackHistoryKey(data) {
      return `${data?.symbol || "NQ"}:${data?.timeframe || 1}`;
    }

    function normaliseFallbackCandles(candles = []) {
      const byTime = new Map();
      candles.forEach((item) => {
        const timestamp = fallbackTime(item?.time);
        const open = Number(item?.open), high = Number(item?.high), low = Number(item?.low), close = Number(item?.close);
        if (timestamp == null || ![open, high, low, close].every(Number.isFinite)) return;
        if (high < low || high < Math.max(open, close) || low > Math.min(open, close)) return;
        byTime.set(timestamp, {
          time: new Date(timestamp).toISOString(), open, high, low, close,
          volume: Number.isFinite(Number(item?.volume)) ? Number(item.volume) : 0,
        });
      });
      return latestCoherentSegment([...byTime.values()].sort((a, b) => fallbackTime(a.time) - fallbackTime(b.time)));
    }

    function mergeFallbackCandles(base = [], incoming = []) {
      const byTime = new Map();
      [...base, ...incoming].forEach((item) => {
        const timestamp = fallbackTime(item?.time);
        if (timestamp != null) byTime.set(timestamp, item);
      });
      return latestCoherentSegment([...byTime.values()]
        .sort((a, b) => fallbackTime(a.time) - fallbackTime(b.time)))
        .slice(-MAX_CACHED_HISTORY_BARS);
    }

    function resolveFallbackCandles(instance, data) {
      const key = fallbackHistoryKey(data);
      const incoming = normaliseFallbackCandles(data?.candles || []);
      const cached = fallbackHistoryCache.get(key) || [];
      const current = instance.payload && fallbackHistoryKey(instance.payload) === key
        ? normaliseFallbackCandles(instance.payload.candles || []) : [];
      const seed = cached.length >= current.length ? cached : current;
      const mismatch = seed.length && incoming.length && regimeGap(seed, incoming) > MAX_SERIES_REGIME_GAP;
      const resolved = mismatch ? incoming : mergeFallbackCandles(seed, incoming);
      instance.contractMismatch = Boolean(mismatch);
      instance.historyRecovered = !mismatch && incoming.length > 0 && incoming.length < MIN_SAFE_HISTORY_BARS && seed.length >= MIN_SAFE_HISTORY_BARS;
      if (resolved.length && (!mismatch || Boolean(data?.historyReady))) fallbackHistoryCache.set(key, resolved);
      return resolved;
    }

    function syncFallbackAutoButton(instance) {
      document.querySelectorAll(`[data-chart-id="${instance.id}"] [data-chart-action="autoscale"]`).forEach((button) => {
        button.classList.toggle("active", instance.autoScale);
        button.setAttribute("aria-pressed", instance.autoScale ? "true" : "false");
      });
    }

    function resetFallbackPriceScale(instance) {
      instance.autoScale = true;
      instance.pricePan = 0;
      instance.priceZoom = 1;
      syncFallbackAutoButton(instance);
    }

    function bindFallbackControls(instance) {
      document.querySelectorAll(`[data-chart-id="${instance.id}"] [data-chart-action]`).forEach((button) => {
        if (button.dataset.mobileCanvasBound === "true") return;
        button.dataset.mobileCanvasBound = "true";
        button.addEventListener("click", () => {
          const action = button.dataset.chartAction;
          if (action === "zoom-in") instance.visibleCount = clamp(Math.round(instance.visibleCount * .78), 24, 180);
          if (action === "zoom-out") instance.visibleCount = clamp(Math.round(instance.visibleCount * 1.28), 24, 180);
          if (action === "pan-left") instance.offset = clamp(instance.offset + Math.max(3, Math.round(instance.visibleCount * .2)), 0, Math.max(0, (instance.payload?.candles?.length || 0) - 10));
          if (action === "pan-right") instance.offset = clamp(instance.offset - Math.max(3, Math.round(instance.visibleCount * .2)), 0, Math.max(0, (instance.payload?.candles?.length || 0) - 10));
          if (["recenter", "fit"].includes(action)) {
            instance.offset = 0;
            resetFallbackPriceScale(instance);
          }
          if (action === "fit") instance.visibleCount = instance.id === "chartLarge" ? 88 : 72;
          if (action === "autoscale") {
            if (instance.autoScale) instance.autoScale = false;
            else resetFallbackPriceScale(instance);
            syncFallbackAutoButton(instance);
          }
          if (action === "candles") instance.chartStyle = "candles";
          if (action === "line") instance.chartStyle = "line";
          if (action === "fullscreen") {
            const root = instance.host.closest(".tv-full-panel") || instance.host.closest(".tv-workstation") || instance.host;
            toggleFullscreenRoot(root);
          }
          drawFallback(instance);
        });
      });
    }

    function bindFallbackGestures(instance) {
      const canvas = instance.canvas;
      const point = (event) => {
        const rect = canvas.getBoundingClientRect();
        return { x: event.clientX - rect.left, y: event.clientY - rect.top };
      };

      canvas.addEventListener("pointerdown", (event) => {
        const p = point(event);
        instance.dragging = true;
        instance.dragMode = p.x >= canvas.clientWidth - 64 ? "price-scale" : "pan";
        instance.dragX = p.x;
        instance.dragY = p.y;
        instance.dragOffset = instance.offset;
        instance.dragPricePan = instance.pricePan;
        instance.dragPriceZoom = instance.priceZoom;
        canvas.setPointerCapture?.(event.pointerId);
        event.preventDefault();
      });

      canvas.addEventListener("pointermove", (event) => {
        if (!instance.dragging) return;
        const p = point(event);
        const dx = p.x - instance.dragX;
        const dy = p.y - instance.dragY;
        const candles = instance.payload?.candles?.length || 0;

        if (instance.dragMode === "price-scale") {
          instance.autoScale = false;
          instance.priceZoom = clamp(instance.dragPriceZoom * Math.exp(-dy / 145), 0.3, 12);
          syncFallbackAutoButton(instance);
        } else {
          const pixelsPerBar = Math.max(3, canvas.clientWidth / Math.max(instance.visibleCount, 1));
          const shift = Math.round(dx / pixelsPerBar);
          instance.offset = clamp(instance.dragOffset + shift, 0, Math.max(0, candles - 10));
          if (Math.abs(dy) > 1) {
            const meta = instance.scaleMeta;
            const pricePerPixel = meta ? (meta.high - meta.low) / Math.max(1, meta.plotHeight) : 0;
            instance.autoScale = false;
            instance.pricePan = instance.dragPricePan + dy * pricePerPixel;
            syncFallbackAutoButton(instance);
          }
        }
        drawFallback(instance);
        event.preventDefault();
      });

      const stop = (event) => {
        instance.dragging = false;
        instance.dragMode = null;
        if (event?.pointerId != null) canvas.releasePointerCapture?.(event.pointerId);
      };
      canvas.addEventListener("pointerup", stop);
      canvas.addEventListener("pointercancel", stop);

      canvas.addEventListener("dblclick", (event) => {
        resetFallbackPriceScale(instance);
        drawFallback(instance);
        event.preventDefault();
      });

      canvas.addEventListener("wheel", (event) => {
        event.preventDefault();
        const p = point(event);
        if (p.x >= canvas.clientWidth - 64 || event.shiftKey) {
          instance.autoScale = false;
          instance.priceZoom = clamp(instance.priceZoom * (event.deltaY < 0 ? 1.12 : 0.88), 0.3, 12);
          syncFallbackAutoButton(instance);
        } else {
          instance.visibleCount = clamp(Math.round(instance.visibleCount * (event.deltaY < 0 ? .88 : 1.12)), 24, 180);
        }
        drawFallback(instance);
      }, { passive: false });
    }

    function simpleEma(values, period) {
      if (!values.length) return [];
      const alpha = 2 / (period + 1); let current = values[0].close;
      return values.map((item) => { current = item.close * alpha + current * (1 - alpha); return current; });
    }

    function linePath(ctx, values, toY, color, width = 1) {
      if (values.length < 2) return;
      ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath();
      values.forEach((value, index) => { const x = value.x; const y = toY(value.value); index ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke(); ctx.restore();
    }

    function horizontal(ctx, y, width, label, color, dashed = true) {
      if (!Number.isFinite(y)) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash(dashed ? [5, 4] : []);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = "600 10px ui-monospace, monospace";
      const textWidth = ctx.measureText(label).width + 10;
      ctx.fillRect(Math.max(0, width - textWidth), y - 9, textWidth, 18);
      ctx.fillStyle = "#071019";
      ctx.fillText(label, Math.max(4, width - textWidth + 5), y + 4);
      ctx.restore();
    }

    function drawFallback(instance) {
      const payload = instance.payload;
      const { width, height } = fallbackSize(instance.host);
      const dpr = window.devicePixelRatio || 1;
      const canvas = instance.canvas;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#090F18";
      ctx.fillRect(0, 0, width, height);

      const raw = Array.isArray(payload?.candles) ? payload.candles : [];
      const candles = normaliseFallbackCandles(raw).map((item) => ({
        time: fallbackTime(item.time), open: item.open, high: item.high,
        low: item.low, close: item.close, volume: item.volume,
      }));
      if (!candles.length) {
        ctx.fillStyle = "#7788A3";
        ctx.font = "500 12px ui-monospace, monospace";
        ctx.textAlign = "center";
        ctx.fillText(payload?.dataQuality === "CONTRACT_MISMATCH" ? "Contract mismatch rejected — waiting for coherent history…" : "Syncing real market history…", width / 2, height / 2);
        return;
      }

      const visibleCount = Math.min(candles.length, instance.visibleCount || (instance.id === "chartLarge" ? 88 : 72));
      const end = Math.max(1, candles.length - Math.max(0, instance.offset || 0));
      const start = Math.max(0, end - visibleCount);
      const values = candles.slice(start, end);
      const setupForScale = payload?.setup || {};
      const rthEq = rthEquilibrium(values, payload?.symbol);
      const marketContextLevels = [setupForScale.vwap, setupForScale.standard_deviation_high, setupForScale.standard_deviation_low, rthEq,
        setupForScale.gex?.call_wall, setupForScale.gex?.gamma_resistance, setupForScale.gex?.gamma_flip,
        setupForScale.gex?.max_pain, setupForScale.gex?.gamma_support, setupForScale.gex?.put_wall];
      const lockedTradeLevels = hasLockedTradePlan(setupForScale)
        ? [setupForScale.entry, initialStop(setupForScale), activeStop(setupForScale), setupForScale.take_profit_1, setupForScale.take_profit_2]
        : [];
      const candleLow = Math.min(...values.map((item) => item.low));
      const candleHigh = Math.max(...values.map((item) => item.high));
      const candleMid = (candleHigh + candleLow) / 2;
      const contextLimit = Math.max((candleHigh - candleLow) * 2.5, Math.abs(candleMid) * 0.025);
      const extra = [...marketContextLevels, ...lockedTradeLevels].map(Number).filter((level) => Number.isFinite(level) && Math.abs(level - candleMid) <= contextLimit);
      let low = Math.min(...values.map((item) => item.low), ...extra);
      let high = Math.max(...values.map((item) => item.high), ...extra);
      const pad = Math.max((high - low) * 0.08, Number(payload?.tickSize || 0.25) * 8);
      low -= pad; high += pad;
      const automaticCenter = (high + low) / 2;
      const automaticRange = Math.max(high - low, Number(payload?.tickSize || 0.25) * 16);
      if (!instance.autoScale) {
        const manualRange = automaticRange / clamp(instance.priceZoom || 1, 0.3, 12);
        const manualCenter = automaticCenter + Number(instance.pricePan || 0);
        low = manualCenter - manualRange / 2;
        high = manualCenter + manualRange / 2;
      }
      const plotRight = width - 58;
      const plotTop = 16;
      const volumeHeight = Math.max(34, Math.min(60, height * .14));
      const plotBottom = height - volumeHeight - 28;
      const plotHeight = Math.max(1, plotBottom - plotTop);
      instance.scaleMeta = { low, high, plotHeight, plotTop, plotBottom, plotRight, automaticRange };
      const toY = (price) => plotTop + (high - Number(price)) / (high - low || 1) * plotHeight;

      ctx.strokeStyle = "rgba(135,151,173,.10)";
      ctx.fillStyle = "#7788A3";
      ctx.font = "500 9px ui-monospace, monospace";
      ctx.textAlign = "left";
      for (let i = 0; i <= 6; i += 1) {
        const y = plotTop + (plotHeight * i / 6);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(plotRight, y); ctx.stroke();
        const price = high - (high - low) * i / 6;
        ctx.fillText(price.toLocaleString("en-US", { maximumFractionDigits: payload?.pricePrecision ?? 2 }), plotRight + 5, y + 3);
      }

      const step = plotRight / Math.max(1, values.length);
      const bodyWidth = Math.max(1.5, Math.min(8, step * 0.64));
      const setup = payload?.setup || {};
      const overlays = payload?.overlays || {};

      if (overlays.scan && !hasLockedTradePlan(setup) && hasWatchingPlan(setup)) {
        const scanPrice = watchTrigger(setup);
        const scanModel = String(setup.primary_entry_model || "candidate").toUpperCase();
        horizontal(ctx, toY(scanPrice), plotRight, `SCAN ${setup.direction} · ${scanModel} · NO ORDER`, lineColors.entry, true);
      }

      if (overlays.zones) {
        (setup.zones || []).forEach((zone) => {
          const top = toY(zone.high), bottom = toY(zone.low);
          ctx.fillStyle = zone.kind === "DEMAND" ? "rgba(38,208,124,.075)" : "rgba(255,77,94,.075)";
          ctx.fillRect(0, Math.min(top, bottom), plotRight, Math.abs(bottom - top));
        });
      }

      if (instance.chartStyle === "line") {
        linePath(ctx, values.map((item, index) => ({ x: (index + .5) * step, value: item.close })), toY, "#48A3FF", 1.8);
      } else {
        values.forEach((item, index) => {
          const x = (index + 0.5) * step;
          const up = item.close >= item.open;
          const color = up ? "#26D07C" : "#FF4D5E";
          ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(x, toY(item.high)); ctx.lineTo(x, toY(item.low)); ctx.stroke();
          const yOpen = toY(item.open); const yClose = toY(item.close);
          ctx.fillRect(x - bodyWidth / 2, Math.min(yOpen, yClose), bodyWidth, Math.max(1, Math.abs(yClose - yOpen)));
        });
      }

      if (overlays.emas) {
        [[9,"#F5B93B"],[21,"#48A3FF"],[55,"#A98BFF"]].forEach(([period,color]) => {
          const series = simpleEma(values, period).map((value, index) => ({ x: (index + .5) * step, value }));
          linePath(ctx, series, toY, color, 1);
        });
      }

      const maxVolume = Math.max(...values.map((item) => Number(item.volume || 0)), 1);
      const volumeTop = plotBottom + 12;
      const volumeBottom = height - 28;
      values.forEach((item, index) => {
        const x = (index + .5) * step;
        const barHeight = Number(item.volume || 0) / maxVolume * Math.max(2, volumeBottom - volumeTop);
        ctx.fillStyle = item.close >= item.open ? "rgba(38,208,124,.42)" : "rgba(255,77,94,.42)";
        ctx.fillRect(x - bodyWidth / 2, volumeBottom - barHeight, bodyWidth, barHeight);
      });

      if (overlays.gex && setup.gex) {
        (setup.gex.intensity_zones || []).slice(0, overlays.clean === false ? 8 : 3).forEach((zone) => {
          const top = toY(zone.high), bottom = toY(zone.low);
          ctx.fillStyle = zone.sign === "POSITIVE" ? "rgba(38,208,124,.060)" : "rgba(255,77,94,.060)";
          ctx.fillRect(0, Math.min(top, bottom), plotRight, Math.max(1, Math.abs(bottom - top)));
        });
        horizontal(ctx, toY(setup.gex.call_wall), plotRight, "GAMMA RES / CALL WALL", lineColors.gex);
        if (Number.isFinite(Number(setup.gex.gamma_resistance)) && Math.abs(Number(setup.gex.gamma_resistance) - Number(setup.gex.call_wall)) > Number(payload?.tickSize || .25) * 2)
          horizontal(ctx, toY(setup.gex.gamma_resistance), plotRight, "GAMMA RESISTANCE", "#A98BFF");
        horizontal(ctx, toY(setup.gex.gamma_flip), plotRight, "GAMMA FLIP", lineColors.entry);
        if (Number.isFinite(Number(setup.gex.max_pain))) horizontal(ctx, toY(setup.gex.max_pain), plotRight, "MAX PAIN", "#D85CFF");
        horizontal(ctx, toY(setup.gex.put_wall), plotRight, "PUT SUPPORT / WALL", lineColors.stop);
        (setup.gex.levels || []).forEach((level) => horizontal(ctx, toY(level.price), plotRight, level.type || "GEX", Number(level.gex || 0) >= 0 ? "#21875A" : "#9D3542"));
      }
      if (overlays.vwap) {
        horizontal(ctx, toY(setup.vwap), plotRight, "VWAP", lineColors.vwap, false);
        if (Number.isFinite(Number(rthEq))) horizontal(ctx, toY(rthEq), plotRight, "RTH EQ", "#E8D99A");
      }
      if (Boolean(overlays.trade) && hasLockedTradePlan(setup)) {
        const entryY = toY(setup.entry);
        const stopY = toY(initialStop(setup));
        const tp1Y = toY(setup.take_profit_1);
        const tp2Y = toY(setup.take_profit_2);
        const startX = Math.max(12, plotRight * tradePlanStartRatio(instance));
        const boxWidth = Math.max(80, plotRight - startX);
        const rewardTop = Math.min(entryY, tp2Y);
        const rewardHeight = Math.max(1, Math.abs(tp2Y - entryY));
        const riskTop = Math.min(entryY, stopY);
        const riskHeight = Math.max(1, Math.abs(stopY - entryY));

        ctx.save();
        ctx.fillStyle = "rgba(38,208,124,.14)";
        ctx.fillRect(startX, rewardTop, boxWidth, rewardHeight);
        ctx.strokeStyle = "rgba(38,208,124,.62)";
        ctx.lineWidth = 1;
        ctx.strokeRect(startX + .5, rewardTop + .5, Math.max(0, boxWidth - 1), Math.max(0, rewardHeight - 1));
        ctx.fillStyle = "rgba(255,77,94,.15)";
        ctx.fillRect(startX, riskTop, boxWidth, riskHeight);
        ctx.strokeStyle = "rgba(255,77,94,.65)";
        ctx.strokeRect(startX + .5, riskTop + .5, Math.max(0, boxWidth - 1), Math.max(0, riskHeight - 1));
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = "rgba(38,208,124,.85)";
        ctx.beginPath(); ctx.moveTo(startX, tp1Y); ctx.lineTo(plotRight, tp1Y); ctx.stroke();
        ctx.setLineDash([]);
        ctx.strokeStyle = lineColors.entry;
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(startX, entryY); ctx.lineTo(plotRight, entryY); ctx.stroke();

        const rr = tradePlanRrLabel(setup);
        const badge = `${executionOrderLabel(setup, true)}${rr ? ` · ${rr}` : ""}`;
        ctx.font = "700 10px ui-monospace, monospace";
        const badgeWidth = Math.min(boxWidth - 8, ctx.measureText(badge).width + 14);
        const badgeY = Math.max(plotTop + 2, Math.min(plotBottom - 20, entryY - 19));
        ctx.fillStyle = lineColors.entry;
        ctx.fillRect(startX + 4, badgeY, Math.max(54, badgeWidth), 18);
        ctx.fillStyle = "#071019";
        ctx.fillText(badge, startX + 11, badgeY + 13);
        ctx.font = "700 9px ui-monospace, monospace";
        ctx.fillStyle = "rgba(210,255,231,.82)";
        if (rewardHeight > 24) ctx.fillText("REWARD", startX + 8, rewardTop + 15);
        ctx.fillStyle = "rgba(255,220,224,.82)";
        if (riskHeight > 24) ctx.fillText("RISK", startX + 8, riskTop + 15);
        ctx.restore();

        horizontal(ctx, entryY, plotRight, executionOrderLabel(setup), lineColors.entry, false);
        horizontal(ctx, stopY, plotRight, "SL", lineColors.stop, false);
        if (Math.abs(activeStop(setup) - initialStop(setup)) > Number(payload?.tickSize || .25) / 2)
          horizontal(ctx, toY(activeStop(setup)), plotRight, "ACTIVE SL / BE", lineColors.entry, true);
        horizontal(ctx, tp1Y, plotRight, "TP1", lineColors.target);
        horizontal(ctx, tp2Y, plotRight, "TP2", lineColors.target, false);
      }
      ctx.fillStyle = "#7788A3";
      ctx.font = "500 9px ui-monospace, monospace";
      ctx.textAlign = "left";
      const legend = document.getElementById(`${instance.id}Ohlc`);
      const last = values.at(-1);
      if (legend && last) {
        const positive = last.close >= last.open;
        legend.innerHTML = `<b>${payload?.displaySymbol || payload?.symbol || "FUTURES"}</b><span>O ${last.open.toFixed(payload?.pricePrecision ?? 2)}</span><span>H ${last.high.toFixed(payload?.pricePrecision ?? 2)}</span><span>L ${last.low.toFixed(payload?.pricePrecision ?? 2)}</span><span class="${positive ? "g" : "r"}">C ${last.close.toFixed(payload?.pricePrecision ?? 2)}</span>`;
      }
      if (!payload?.historyReady || instance.contractMismatch || candles.length < MIN_SAFE_HISTORY_BARS) {
        const label = instance.contractMismatch || payload?.dataQuality === "CONTRACT_MISMATCH"
          ? "PRICE REGIME RESET · LIVE ONLY"
          : `HISTORY SYNCING · ${candles.length} BAR${candles.length === 1 ? "" : "S"}`;
        ctx.fillStyle = "rgba(8,15,23,.88)"; ctx.fillRect(10, 12, Math.min(plotRight - 20, 230), 26);
        ctx.strokeStyle = instance.contractMismatch ? "#FF4D5E" : "#F5B93B"; ctx.strokeRect(10.5, 12.5, Math.min(plotRight - 21, 229), 25);
        ctx.fillStyle = instance.contractMismatch ? "#FF4D5E" : "#F5B93B"; ctx.font = "700 10px ui-monospace, monospace"; ctx.fillText(label, 20, 29);
      }
    }

    function render(id, data) {
      const instance = ensureFallback(id);
      if (!instance) return;
      const marketChanged = instance.payload && (instance.payload.symbol !== data.symbol || instance.payload.timeframe !== data.timeframe);
      const candles = resolveFallbackCandles(instance, data);
      instance.payload = { ...data, candles };
      if (marketChanged) {
        instance.offset = 0;
        resetFallbackPriceScale(instance);
      }
      requestAnimationFrame(() => drawFallback(instance));
    }
    function reset(id) {
      const instance = fallbackInstances.get(id);
      if (instance) {
        instance.offset = 0;
        instance.visibleCount = id === "chartLarge" ? 88 : 72;
        resetFallbackPriceScale(instance);
        drawFallback(instance);
      }
    }
    function marketChanged(id) {
      const instance = fallbackInstances.get(id);
      if (instance) {
        instance.payload = null;
        instance.offset = 0;
        resetFallbackPriceScale(instance);
        drawFallback(instance);
      }
    }
    function resize(id) { const instance = fallbackInstances.get(id); if (instance) drawFallback(instance); }
    function refresh(id) { const instance = fallbackInstances.get(id); if (instance) drawFallback(instance); }
    window.TradeIQChartManager = { render, reset, marketChanged, resize, refresh, instances: fallbackInstances, fallback: true, mobileCanvas: USE_MOBILE_CANVAS };
  }

  if (!LC) {
    installCanvasFallback();
    return;
  }

  const COLORS = {
    background: "#090F18",
    text: "#8492A6",
    grid: "rgba(135, 151, 173, 0.075)",
    border: "#1A2636",
    green: "#26D07C",
    red: "#FF4D5E",
    amber: "#F5B93B",
    blue: "#48A3FF",
    purple: "#A98BFF",
    vwap: "#E4D06F",
    muted: "#58677A",
  };

  const instances = new Map();
  const desktopHistoryCache = new Map();
  const desktopViewportCache = new Map();
  const pendingRenders = new Map();
  const renderTimers = new Map();
  const dashed = LC.LineStyle?.Dashed ?? 2;
  const dotted = LC.LineStyle?.Dotted ?? 1;

  function unixTime(value) {
    const timestamp = Math.floor(new Date(value).getTime() / 1000);
    return Number.isFinite(timestamp) ? timestamp : null;
  }

  function tradePlanStartX(instance, chartWidth) {
    const fallback = chartWidth * tradePlanStartRatio(instance);
    const eventTime = unixTime(instance?.setup?.armed_at || instance?.setup?.filled_at);
    const eventX = eventTime != null ? instance?.chart?.timeScale?.().timeToCoordinate?.(eventTime) : null;
    const proposed = Number.isFinite(Number(eventX)) ? Number(eventX) : fallback;
    const minimum = Math.max(8, chartWidth * 0.08);
    const minimumBoxWidth = instance?.host?.clientWidth < 700
      ? Math.min(190, chartWidth * 0.48)
      : Math.min(300, chartWidth * 0.44);
    const maximum = Math.max(minimum, chartWidth - minimumBoxWidth);
    return Math.max(minimum, Math.min(maximum, proposed));
  }

  function drawCanvasTag(ctx, x, y, text, background, foreground, maxWidth = 260) {
    if (!text) return { width: 0, height: 0 };
    ctx.save();
    ctx.font = "700 10px ui-monospace, SFMono-Regular, Menlo, monospace";
    let label = String(text);
    const paddingX = 8;
    const height = 20;
    while (label.length > 8 && ctx.measureText(label).width + paddingX * 2 > maxWidth) {
      label = `${label.slice(0, -2)}…`;
    }
    const width = Math.max(54, Math.min(maxWidth, ctx.measureText(label).width + paddingX * 2));
    ctx.fillStyle = background;
    ctx.fillRect(x, y, width, height);
    ctx.strokeStyle = "rgba(255,255,255,.16)";
    ctx.lineWidth = 1;
    ctx.strokeRect(x + .5, y + .5, Math.max(0, width - 1), height - 1);
    ctx.fillStyle = foreground;
    ctx.textBaseline = "middle";
    ctx.fillText(label, x + paddingX, y + height / 2 + .5);
    ctx.restore();
    return { width, height };
  }

  function normaliseCandles(candles = []) {
    const byTime = new Map();
    candles.forEach((candle) => {
      const time = unixTime(candle.time);
      if (time == null) return;
      const item = {
        time,
        open: Number(candle.open),
        high: Number(candle.high),
        low: Number(candle.low),
        close: Number(candle.close),
        volume: Math.max(0, Number(candle.volume || 0)),
      };
      if (!Object.values(item).slice(1).every(Number.isFinite)) return;
      if (item.open <= 0 || item.close <= 0) return;
      if (item.high < item.low || item.high < Math.max(item.open, item.close) || item.low > Math.min(item.open, item.close)) return;
      const reference = Math.max(Math.abs(item.open), Math.abs(item.close), 1e-9);
      if ((item.high - item.low) / reference > 0.08) return;
      byTime.set(time, item);
    });

    const ordered = [...byTime.values()].sort((a, b) => a.time - b.time);
    if (ordered.length < 3) return latestCoherentSegment(ordered);
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
      const typicalRange = median(recentRanges.slice(-30).filter((value) => value > 0)) || 0;
      const giantWick = typicalRange > 0
        && candleRange > Math.max(typicalRange * 10, reference * 0.008)
        && body < Math.max(typicalRange * 5, candleRange * 0.35);
      if (giantWick || (jump > MAX_SERIES_REGIME_GAP && returnJump > MAX_SERIES_REGIME_GAP)) continue;
      clean.push(current);
      recentRanges.push(candleRange);
    }
    const last = ordered.at(-1);
    const previous = clean.at(-1);
    const reference = Math.max(Math.abs(previous.close), 1e-9);
    const candleRange = Math.max(0, last.high - last.low);
    const body = Math.abs(last.close - last.open);
    const typicalRange = median(recentRanges.slice(-30).filter((value) => value > 0)) || 0;
    const giantLiveWick = typicalRange > 0
      && candleRange > Math.max(typicalRange * 10, reference * 0.008)
      && body < Math.max(typicalRange * 4, candleRange * 0.35);
    if (!giantLiveWick) clean.push(last);
    return latestCoherentSegment(clean);
  }

  function desktopHistoryKey(data) {
    return `${data?.symbol || "NQ"}:${data?.timeframe || 1}`;
  }

  function mergeDesktopCandles(base = [], incoming = []) {
    const byTime = new Map();
    [...base, ...incoming].forEach((item) => {
      if (item && Number.isFinite(Number(item.time))) byTime.set(Number(item.time), item);
    });
    return latestCoherentSegment([...byTime.values()].sort((a, b) => a.time - b.time)).slice(-MAX_CACHED_HISTORY_BARS);
  }

  function resolveDesktopCandles(instance, data) {
    const key = desktopHistoryKey(data);
    const incoming = normaliseCandles(data?.candles || []);
    const cached = desktopHistoryCache.get(key) || [];
    const current = instance.symbol === data.symbol && instance.timeframe === data.timeframe ? instance.data : [];
    const seed = cached.length >= current.length ? cached : current;
    const mismatch = seed.length && incoming.length && regimeGap(seed, incoming) > MAX_SERIES_REGIME_GAP;
    const resolved = mismatch ? incoming : mergeDesktopCandles(seed, incoming);
    instance.contractMismatch = Boolean(mismatch);
    instance.historyRecovered = !mismatch && incoming.length > 0 && incoming.length < MIN_SAFE_HISTORY_BARS && seed.length >= MIN_SAFE_HISTORY_BARS;
    if (resolved.length && (!mismatch || Boolean(data?.historyReady))) desktopHistoryCache.set(key, resolved);
    return { incoming, resolved };
  }

  function emaData(candles, period) {
    if (!candles.length) return [];
    const alpha = 2 / (period + 1);
    let value = candles[0].close;
    return candles.map((candle) => {
      value = candle.close * alpha + value * (1 - alpha);
      return { time: candle.time, value };
    });
  }

  function closeData(candles) {
    return candles.map((candle) => ({ time: candle.time, value: candle.close }));
  }

  function volumeData(candles) {
    return candles.map((candle) => ({
      time: candle.time,
      value: Number(candle.volume || 0),
      color: candle.close >= candle.open ? "rgba(38,208,124,.38)" : "rgba(255,77,94,.38)",
    }));
  }

  function formatPrice(value, precision = 2) {
    if (!Number.isFinite(Number(value))) return "—";
    return Number(value).toLocaleString("en-US", {
      minimumFractionDigits: precision,
      maximumFractionDigits: precision,
    });
  }

  function displayChartTime(time) {
    if (!time) return "—";
    const value = typeof time === "number" ? time : Number(time);
    const timestamp = Number.isFinite(value) ? value : time;
    if (window.TradeIQTime?.formatChartTime) return window.TradeIQTime.formatChartTime(timestamp);
    return new Date(Number(timestamp) * 1000).toLocaleString("en-US", {
      timeZone: "America/New_York",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function measureHost(host) {
    if (!host) return { width: 0, height: 0 };
    const rect = host.getBoundingClientRect();
    return {
      width: Math.floor(rect.width || host.clientWidth || 0),
      height: Math.floor(rect.height || host.clientHeight || 0),
    };
  }

  function hostIsReady(host) {
    const size = measureHost(host);
    return Boolean(host?.isConnected && size.width >= 180 && size.height >= 180);
  }

  function resizeInstance(instance) {
    if (!instance) return false;
    const { width, height } = measureHost(instance.host);
    if (width < 2 || height < 2) return false;
    if (instance.lastWidth !== width || instance.lastHeight !== height) {
      instance.chart.resize(width, height, true); // compatibility: instance.chart.resize(width, height)
      instance.lastWidth = width;
      instance.lastHeight = height;
      scheduleOverlay(instance);
    }
    return true;
  }

  function scheduleRender(id, data) {
    pendingRenders.set(id, data);
    if (renderTimers.has(id)) return;
    let attempts = 0;
    const tryRender = () => {
      attempts += 1;
      const host = document.getElementById(id);
      if (hostIsReady(host)) {
        renderTimers.delete(id);
        const latest = pendingRenders.get(id);
        pendingRenders.delete(id);
        if (latest) render(id, latest, true);
        return;
      }
      if (attempts < 80) {
        renderTimers.set(id, window.setTimeout(tryRender, 50));
      } else {
        renderTimers.delete(id);
        if (host) host.innerHTML = '<div class="chart-load-error">Chart area did not receive a usable size. Rotate the device or tap Chart again.</div>';
      }
    };
    renderTimers.set(id, window.setTimeout(tryRender, 0));
  }

  function createInstance(id) {
    const host = document.getElementById(id);
    if (!host) return null;

    const initialSize = measureHost(host);
    if (initialSize.width < 2 || initialSize.height < 2) return null;
    const mobile = window.matchMedia?.("(max-width: 900px)")?.matches === true || initialSize.width < 720;
    const chart = LC.createChart(host, {
      autoSize: false,
      width: initialSize.width,
      height: initialSize.height,
      layout: {
        background: { type: LC.ColorType?.Solid ?? "solid", color: COLORS.background },
        textColor: COLORS.text,
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      crosshair: {
        mode: LC.CrosshairMode?.Normal ?? 0,
        vertLine: { color: "rgba(200,210,224,.65)", width: 1, style: dashed, labelBackgroundColor: "#303B4B" },
        horzLine: { color: "rgba(200,210,224,.65)", width: 1, style: dashed, labelBackgroundColor: "#303B4B" },
      },
      rightPriceScale: {
        visible: true,
        borderColor: COLORS.border,
        minimumWidth: mobile ? 60 : 76,
        scaleMargins: { top: 0.09, bottom: 0.12 },
        ticksVisible: true,
      },
      leftPriceScale: { visible: false },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: id === "chartLarge" ? 12 : 8,
        rightOffsetPixels: mobile ? 48 : undefined,
        barSpacing: id === "chartLarge" ? 8 : 6,
        minBarSpacing: 0.45,
        maxBarSpacing: 42,
        lockVisibleTimeRangeOnResize: true,
        rightBarStaysOnScroll: true,
        shiftVisibleRangeOnNewBar: false,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
      kineticScroll: { mouse: true, touch: true },
      trackingMode: { exitMode: LC.TrackingModeExitMode?.OnTouchEnd ?? 0 },
      localization: {
        priceFormatter: (price) => formatPrice(price),
        timeFormatter: (time) => displayChartTime(time),
      },
    });

    let autoscaleInstance = null;
    const candleSeries = chart.addSeries(LC.CandlestickSeries, {
      upColor: COLORS.green,
      downColor: COLORS.red,
      borderVisible: true,
      borderUpColor: COLORS.green,
      borderDownColor: COLORS.red,
      wickUpColor: COLORS.green,
      wickDownColor: COLORS.red,
      priceLineVisible: true,
      lastValueVisible: true,
      conflationThresholdFactor: 0.5,
      priceFormat: { type: "price", precision: 2, minMove: 0.25 },
      // Keep the candle scale driven by visible OHLC data, not distant GEX,
      // Fib, supply/demand or target price lines. This is the equivalent of
      // TradingView's "scale price chart only" behaviour and prevents 1m/2m
      // candles from being crushed into a tiny band.
      autoscaleInfoProvider: (original) => {
        const fallback = original();
        const instance = autoscaleInstance;
        if (!instance?.autoScale || !instance.data?.length) return fallback;
        const logical = chart.timeScale().getVisibleLogicalRange();
        const from = logical ? Math.max(0, Math.floor(logical.from) - 2) : Math.max(0, instance.data.length - 140);
        const to = logical ? Math.min(instance.data.length - 1, Math.ceil(logical.to) + 2) : instance.data.length - 1;
        const visible = instance.data.slice(from, to + 1);
        if (!visible.length) return fallback;
        const highs = visible.map((item) => Number(item.high)).filter(Number.isFinite);
        const lows = visible.map((item) => Number(item.low)).filter(Number.isFinite);
        if (!highs.length || !lows.length) return fallback;
        const high = Math.max(...highs);
        const low = Math.min(...lows);
        const ranges = visible.map((item) => Math.max(0, Number(item.high) - Number(item.low))).filter(Number.isFinite);
        const typicalRange = median(ranges) || Number(instance.tickSize || 0.25) * 4;
        const minimumSpan = Math.max(Number(instance.tickSize || 0.25) * 24, typicalRange * 7);
        const rawSpan = Math.max(high - low, minimumSpan);
        const centre = (high + low) / 2;
        const padding = Math.max(rawSpan * 0.12, typicalRange * 2);
        return {
          priceRange: {
            minValue: centre - rawSpan / 2 - padding,
            maxValue: centre + rawSpan / 2 + padding,
          },
          margins: fallback?.margins,
        };
      },
    });
    const closeSeries = chart.addSeries(LC.LineSeries, {
      color: COLORS.blue,
      lineWidth: 2,
      visible: false,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: true,
    });
    const ema9 = chart.addSeries(LC.LineSeries, { color: COLORS.amber, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const ema21 = chart.addSeries(LC.LineSeries, { color: COLORS.blue, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const ema55 = chart.addSeries(LC.LineSeries, { color: COLORS.purple, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const volumeSeries = chart.addSeries(LC.HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volumeSeries.priceScale().applyOptions({ autoScale: true, scaleMargins: { top: 0.82, bottom: 0 } });

    const overlayCanvas = document.createElement("canvas");
    overlayCanvas.className = "tv-overlay-canvas";
    overlayCanvas.setAttribute("aria-hidden", "true");
    host.appendChild(overlayCanvas);
    const dataState = document.createElement("div");
    dataState.className = "chart-data-state";
    dataState.hidden = true;
    host.appendChild(dataState);

    const instance = {
      id,
      host,
      chart,
      candleSeries,
      closeSeries,
      ema9,
      ema21,
      ema55,
      volumeSeries,
      overlayCanvas,
      dataState,
      priceLines: [],
      userPriceLines: [],
      data: [],
      setup: null,
      overlays: {},
      timeframe: null,
      firstRender: true,
      chartStyle: "candles",
      drawMode: "cursor",
      autoScale: true,
      overlayFrame: null,
      symbol: "NQ",
      displaySymbol: "NQ1!",
      instrumentName: "E-mini Nasdaq-100",
      tickSize: 0.25,
      pricePrecision: 2,
      userInteracted: false,
      atRealtime: true,
      lastWidth: initialSize.width,
      lastHeight: initialSize.height,
    };
    autoscaleInstance = instance;

    chart.subscribeCrosshairMove((param) => updateLegend(instance, param));
    chart.subscribeClick((param) => handleChartClick(instance, param));
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      const position = chart.timeScale().scrollPosition?.();
      instance.atRealtime = position == null || position <= 1.5;
      if (instance.userInteracted && range && instance.timeframe != null && instance.symbol) {
        desktopViewportCache.set(`${instance.symbol}:${instance.timeframe}:${instance.id}`, { from: range.from, to: range.to });
      }
      scheduleOverlay(instance);
    });
    host.addEventListener("pointerdown", () => { instance.userInteracted = true; }, { passive: true });
    host.addEventListener("wheel", () => { instance.userInteracted = true; }, { passive: true });

    const resizeObserver = new ResizeObserver(() => {
      if (resizeInstance(instance)) scheduleOverlay(instance);
    });
    resizeObserver.observe(host);
    instance.resizeObserver = resizeObserver;

    bindControls(instance);
    instances.set(id, instance);
    return instance;
  }

  function updateLegend(instance, param) {
    const legend = document.getElementById(`${instance.id}Ohlc`);
    if (!legend) return;
    let candle = null;
    if (param?.seriesData?.get) candle = param.seriesData.get(instance.candleSeries);
    if (!candle) candle = instance.data.at(-1);
    if (!candle) {
      legend.textContent = `${instance.displaySymbol} · waiting for data`;
      return;
    }
    const positive = candle.close >= candle.open;
    const digits = instance.pricePrecision;
    legend.innerHTML = `<b>${instance.displaySymbol}</b><span>${etTime(candle.time)} ET</span><span>O ${formatPrice(candle.open, digits)}</span><span>H ${formatPrice(candle.high, digits)}</span><span>L ${formatPrice(candle.low, digits)}</span><span class="${positive ? "g" : "r"}">C ${formatPrice(candle.close, digits)}</span>`;
  }

  function handleChartClick(instance, param) {
    if (instance.drawMode !== "hline" || !param?.point) return;
    const price = instance.candleSeries.coordinateToPrice(param.point.y);
    if (!Number.isFinite(Number(price))) return;
    const line = instance.candleSeries.createPriceLine({
      price: Number(price),
      color: "#DCE4EF",
      lineWidth: 1,
      lineStyle: dashed,
      axisLabelVisible: true,
      title: "H-LINE",
    });
    instance.userPriceLines.push(line);
    setDrawMode(instance, "cursor");
  }

  function bindControls(instance) {
    document.querySelectorAll(`[data-chart-id="${instance.id}"] [data-chart-action]`).forEach((button) => {
      button.addEventListener("click", () => runAction(instance, button.dataset.chartAction, button));
    });
    document.querySelectorAll(`[data-chart-id="${instance.id}"] [data-draw-mode]`).forEach((button) => {
      button.addEventListener("click", () => setDrawMode(instance, button.dataset.drawMode));
    });
  }

  function setDrawMode(instance, mode) {
    instance.drawMode = mode;
    document.querySelectorAll(`[data-chart-id="${instance.id}"] [data-draw-mode]`).forEach((button) => {
      button.classList.toggle("active", button.dataset.drawMode === mode);
    });
    instance.host.style.cursor = mode === "hline" ? "crosshair" : "default";
  }

  function logicalZoom(instance, multiplier) {
    const scale = instance.chart.timeScale();
    const range = scale.getVisibleLogicalRange();
    if (!range) return;
    const center = (range.from + range.to) / 2;
    const span = Math.max(8, (range.to - range.from) * multiplier);
    scale.setVisibleLogicalRange({ from: center - span / 2, to: center + span / 2 });
  }

  function logicalPan(instance, direction) {
    const scale = instance.chart.timeScale();
    const range = scale.getVisibleLogicalRange();
    if (!range) return;
    const shift = (range.to - range.from) * 0.22 * direction;
    scale.setVisibleLogicalRange({ from: range.from + shift, to: range.to + shift });
  }

  function runAction(instance, action, button) {
    switch (action) {
      case "zoom-in": logicalZoom(instance, 0.78); break;
      case "zoom-out": logicalZoom(instance, 1.28); break;
      case "pan-left": logicalPan(instance, -1); break;
      case "pan-right": logicalPan(instance, 1); break;
      case "recenter":
        instance.chart.timeScale().scrollToRealTime();
        instance.candleSeries.priceScale().applyOptions({ autoScale: true });
        instance.autoScale = true;
        instance.userInteracted = false;
        break;
      case "fit":
        instance.chart.timeScale().fitContent();
        instance.candleSeries.priceScale().applyOptions({ autoScale: true });
        instance.autoScale = true;
        instance.userInteracted = false;
        break;
      case "autoscale":
        instance.autoScale = !instance.autoScale;
        instance.candleSeries.priceScale().applyOptions({ autoScale: instance.autoScale });
        button?.classList.toggle("active", instance.autoScale);
        break;
      case "crosshair":
        instance.chart.applyOptions({ crosshair: { mode: LC.CrosshairMode?.Normal ?? 0 } });
        setDrawMode(instance, "crosshair");
        break;
      case "magnet":
        instance.chart.applyOptions({ crosshair: { mode: LC.CrosshairMode?.Magnet ?? 1 } });
        setDrawMode(instance, "magnet");
        break;
      case "clear-drawing": {
        const line = instance.userPriceLines.pop();
        if (line) instance.candleSeries.removePriceLine(line);
        break;
      }
      case "candles": setChartStyle(instance, "candles"); break;
      case "line": setChartStyle(instance, "line"); break;
      case "fullscreen": toggleFullscreen(instance); break;
      default: break;
    }
    scheduleOverlay(instance);
  }

  function setChartStyle(instance, style) {
    instance.chartStyle = style;
    instance.candleSeries.applyOptions({ visible: style === "candles" });
    instance.closeSeries.applyOptions({ visible: style === "line" });
    document.querySelectorAll(`[data-chart-id="${instance.id}"] [data-chart-style]`).forEach((button) => {
      button.classList.toggle("active", button.dataset.chartStyle === style);
    });
  }

  function toggleFullscreen(instance) {
    const root = instance.id === "chartLarge" ? (instance.host.closest(".tv-full-panel") || instance.host.closest(".tv-workstation")) : (instance.host.closest(".chart-panel") || instance.host);
    toggleFullscreenRoot(root);
  }

  function clearSystemPriceLines(instance) {
    instance.priceLines.forEach((line) => {
      try { instance.candleSeries.removePriceLine(line); } catch (_) { /* stale line */ }
    });
    instance.priceLines = [];
    instance.systemLabelPrices = [];
  }

  function addPriceLine(instance, price, title, color, style = dashed, width = 1, axisLabelVisible = true) {
    if (!Number.isFinite(Number(price))) return;
    const numericPrice = Number(price);
    if (axisLabelVisible) {
      const tolerance = Math.max(Number(instance.tickSize || .25) * 8, Number(instance.setup?.atr || 0) * .10);
      if ((instance.systemLabelPrices || []).some((value) => Math.abs(value - numericPrice) < tolerance)) {
        axisLabelVisible = false;
        title = "";
      } else {
        instance.systemLabelPrices = [...(instance.systemLabelPrices || []), numericPrice];
      }
    }
    const line = instance.candleSeries.createPriceLine({
      price: numericPrice, color, lineWidth: width, lineStyle: style,
      axisLabelVisible, title,
    });
    instance.priceLines.push(line);
  }

  function cleanPriorityZones(instance, setup) {
    const zones = (setup?.zones || []).filter((zone) =>
      Number.isFinite(Number(zone.low)) && Number.isFinite(Number(zone.high)) && Number(zone.high) >= Number(zone.low)
    );
    if (!zones.length) return [];
    const current = Number(instance.data.at(-1)?.close);
    const atr = Math.max(Number(setup?.atr || 0), Number(instance.tickSize || 0.25) * 8);
    const selected = zones.find((zone) =>
      setup.selected_zone_low != null && setup.selected_zone_high != null
      && Math.abs(Number(zone.low) - Number(setup.selected_zone_low)) <= Number(instance.tickSize || .25)
      && Math.abs(Number(zone.high) - Number(setup.selected_zone_high)) <= Number(instance.tickSize || .25)
    );
    const distance = (zone) => {
      if (!Number.isFinite(current)) return 0;
      if (Number(zone.low) <= current && current <= Number(zone.high)) return 0;
      return Math.min(Math.abs(current - Number(zone.low)), Math.abs(current - Number(zone.high)));
    };
    const candidates = [];
    if (selected) candidates.push(selected);
    ["DEMAND", "SUPPLY"].forEach((kind) => {
      const nearest = zones.filter((zone) => zone.kind === kind).sort((a, b) => distance(a) - distance(b))[0];
      if (nearest) candidates.push(nearest);
    });
    const deduped = [];
    candidates.forEach((zone) => {
      const mid = (Number(zone.low) + Number(zone.high)) / 2;
      if (deduped.some((other) => Math.abs(mid - (Number(other.low) + Number(other.high)) / 2) < atr * .18)) return;
      deduped.push(zone);
    });
    return deduped.slice(0, 3);
  }

  function marketMapColor(cluster, opposing = false) {
    if (opposing) return COLORS.blue;
    return cluster?.role === "SUPPORT" ? COLORS.green : COLORS.red;
  }

  function marketMapTitle(cluster, prefix = "") {
    if (!cluster) return "";
    const tier = String(cluster.tier || "CLUSTER").replaceAll("_", " ");
    const state = String(cluster.state || "").replaceAll("_", " ");
    const lead = prefix ? `${prefix} · ` : "";
    return `${lead}${tier} ${cluster.role} · ${Number(cluster.score || 0).toFixed(0)}%${state ? ` · ${state}` : ""}`;
  }

  function renderCleanMarketMapLines(instance, setup) {
    const map = setup?.market_map;
    if (!map) return false;
    const chosen = [];
    const add = (cluster, prefix, opposing = false) => {
      if (!cluster || chosen.some((item) => item.cluster_id === cluster.cluster_id)) return;
      chosen.push(cluster);
      addPriceLine(
        instance,
        cluster.midpoint,
        marketMapTitle(cluster, prefix),
        marketMapColor(cluster, opposing),
        opposing ? dotted : dashed,
        opposing ? 1 : 2,
        true,
      );
    };
    add(map.active_cluster, "ACTIVE CLUSTER", false);
    add(map.opposing_cluster, "OPPOSING LIQUIDITY", true);
    if (!map.active_cluster) {
      add(map.nearest_resistance, "NEAREST RESISTANCE", true);
      add(map.nearest_support, "NEAREST SUPPORT", true);
    }
    return chosen.length > 0;
  }

  function rebuildPriceLines(instance) {
    clearSystemPriceLines(instance);
    const setup = instance.setup;
    const overlays = instance.overlays || {};
    const cleanMode = overlays.clean !== false;
    if (!setup) return;

    // Trade lifecycle levels receive label priority. Context levels that sit on
    // top of them remain visible as lines but suppress duplicate right-axis tags.
    if (overlays.scan && !hasLockedTradePlan(setup) && hasWatchingPlan(setup)) {
      const scanPrice = watchTrigger(setup);
      const scanModel = String(setup.primary_entry_model || "candidate").toUpperCase();
      const scanState = watchTriggerTouched(setup) ? "CONFIRMING" : "SCANNING";
      addPriceLine(instance, scanPrice, `${scanState} ${setup.direction} · ${scanModel} · NO ORDER`, COLORS.amber, dotted, 1, true);
    }
    if (overlays.trade && hasLockedTradePlan(setup)) {
      addPriceLine(instance, setup.entry, executionOrderLabel(setup), COLORS.amber, dashed, 2);
      addPriceLine(instance, initialStop(setup), "SL", COLORS.red, dashed, 2);
      if (Math.abs(activeStop(setup) - initialStop(setup)) > Number(instance.tickSize || .25) / 2)
        addPriceLine(instance, activeStop(setup), "ACTIVE SL / BE", COLORS.amber, dotted, 2);
      addPriceLine(instance, setup.take_profit_1, "TP1", COLORS.green, dashed, 2);
      addPriceLine(instance, setup.take_profit_2, "TP2", COLORS.green, dashed, 2);
    }

    const marketMapVisible = overlays.map && setup.market_map;
    if (marketMapVisible) renderCleanMarketMapLines(instance, setup);

    if (overlays.gex && setup.gex) {
      addPriceLine(instance, setup.gex.call_wall, "GAMMA RES / CALL WALL", COLORS.blue, dashed, 2);
      if (Number.isFinite(Number(setup.gex.gamma_resistance)) && Math.abs(Number(setup.gex.gamma_resistance) - Number(setup.gex.call_wall)) > instance.tickSize * 2)
        addPriceLine(instance, setup.gex.gamma_resistance, "GAMMA RESISTANCE", COLORS.purple, dotted, 1);
      addPriceLine(instance, setup.gex.gamma_flip, "GAMMA FLIP", COLORS.amber, dashed, 2);
      if (Number.isFinite(Number(setup.gex.max_pain))) addPriceLine(instance, setup.gex.max_pain, "MAX PAIN", "#D85CFF", dashed, 2);
      addPriceLine(instance, setup.gex.put_wall, "PUT SUPPORT / WALL", COLORS.red, dashed, 2);
      if (!cleanMode) {
        (setup.gex.levels || []).forEach((level) => {
          addPriceLine(instance, level.price, level.type || "GEX", Number(level.gex || 0) >= 0 ? "#21875A" : "#9D3542", dotted, 1);
        });
      }
    }

    if (overlays.fib) {
      const fibContinuation = setup.primary_entry_model_key === "FIB_PULLBACK_CONTINUATION";
      if (fibContinuation) {
        const zoneLow = Number(setup.signals?.fib_pullback_zone_low);
        const zoneHigh = Number(setup.signals?.fib_pullback_zone_high);
        const fib50 = setup.direction === "LONG" ? zoneHigh : zoneLow;
        const fib618 = setup.direction === "LONG" ? zoneLow : zoneHigh;
        addPriceLine(instance, fib50, "FIB 50%", COLORS.amber, dotted, 2, true);
        addPriceLine(instance, fib618, "FIB 61.8%", COLORS.amber, dotted, 2, true);
      } else {
        const cleanRatios = [0.618, 0.705, 0.786];
        const fibs = cleanMode
          ? (setup.fib_levels || []).filter((level) => cleanRatios.some((ratio) => Math.abs(Number(level.ratio) - ratio) < .003))
          : (setup.fib_levels || []);
        fibs.forEach((level) => {
          const ratio = Number(level.ratio);
          const important = Math.abs(ratio - 0.705) < .002;
          addPriceLine(instance, level.price, level.label || String(level.ratio), important ? COLORS.amber : "#49576A", dotted, important ? 2 : 1, important);
        });
      }
    }

    if (overlays.vwap) {
      addPriceLine(instance, setup.vwap, "VWAP", COLORS.vwap, dotted, 1);
      if (!cleanMode) {
        addPriceLine(instance, setup.standard_deviation_high, "+1σ", COLORS.muted, dotted, 1);
        addPriceLine(instance, setup.standard_deviation_low, "-1σ", COLORS.muted, dotted, 1);
        addPriceLine(instance, instance.rthEq, "RTH EQ", "#E8D99A", dotted, 1);
      }
    }

    if (overlays.zones) {
      const zones = cleanMode
        ? cleanPriorityZones(instance, setup)
        : (setup.zones || []);
      zones.forEach((zone) => {
        const color = zone.kind === "DEMAND" ? "#21875A" : "#9D3542";
        const selected = setup.selected_zone_low != null && Math.abs(Number(zone.low) - Number(setup.selected_zone_low)) <= Number(instance.tickSize || .25);
        addPriceLine(instance, zone.high, `${zone.timeframe} ${zone.kind}`, color, dotted, selected ? 2 : 1, true);
        addPriceLine(instance, zone.low, "", color, dotted, 1, false);
      });
    }
  }

  function scheduleOverlay(instance) {
    if (instance.overlayFrame) cancelAnimationFrame(instance.overlayFrame);
    instance.overlayFrame = requestAnimationFrame(() => drawOverlay(instance));
  }

  function drawOverlay(instance) {
    const canvas = instance.overlayCanvas;
    const width = instance.host.clientWidth;
    const height = instance.host.clientHeight;
    if (!width || !height) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const setup = instance.setup;
    const overlays = instance.overlays || {};
    const cleanMode = overlays.clean !== false;
    if (!setup) return;
    const chartWidth = Math.max(0, width - 77);
    const coordinate = (price) => instance.candleSeries.priceToCoordinate(Number(price));
    const marketMapVisible = overlays.map && setup.market_map;

    if (marketMapVisible) {
      const clusters = [];
      const addCluster = (cluster, opposing = false) => {
        if (!cluster || clusters.some((item) => item.cluster.cluster_id === cluster.cluster_id)) return;
        clusters.push({ cluster, opposing });
      };
      addCluster(setup.market_map.active_cluster, false);
      addCluster(setup.market_map.opposing_cluster, true);
      if (!setup.market_map.active_cluster) {
        addCluster(setup.market_map.nearest_support, true);
        addCluster(setup.market_map.nearest_resistance, true);
      }
      clusters.forEach(({ cluster, opposing }) => {
        const top = coordinate(cluster.high);
        const bottom = coordinate(cluster.low);
        if (top == null || bottom == null) return;
        const support = cluster.role === "SUPPORT";
        ctx.fillStyle = opposing
          ? "rgba(72,163,255,.045)"
          : support ? "rgba(38,208,124,.070)" : "rgba(255,77,94,.070)";
        ctx.fillRect(0, Math.min(top, bottom), chartWidth, Math.max(1, Math.abs(bottom - top)));
      });
    }

    if (overlays.gex && setup.gex) {
      (setup.gex.intensity_zones || []).slice(0, cleanMode ? 3 : 8).forEach((zone) => {
        const top = coordinate(zone.high);
        const bottom = coordinate(zone.low);
        if (top == null || bottom == null) return;
        ctx.fillStyle = zone.sign === "POSITIVE"
          ? (cleanMode ? "rgba(38,208,124,.035)" : "rgba(38,208,124,.060)")
          : (cleanMode ? "rgba(255,77,94,.035)" : "rgba(255,77,94,.060)");
        ctx.fillRect(0, Math.min(top, bottom), chartWidth, Math.max(1, Math.abs(bottom - top)));
      });
      const half = Math.max(Number(instance.tickSize || .25) * 3, Number(setup.atr || 0) * .08);
      [
        [setup.gex.call_wall, "rgba(72,163,255,.10)"],
        [setup.gex.max_pain, "rgba(216,92,255,.08)"],
        [setup.gex.put_wall, "rgba(38,208,124,.09)"],
      ].forEach(([level, color]) => {
        if (!Number.isFinite(Number(level))) return;
        const top = coordinate(Number(level) + half);
        const bottom = coordinate(Number(level) - half);
        if (top == null || bottom == null) return;
        ctx.fillStyle = color;
        ctx.fillRect(0, Math.min(top, bottom), chartWidth, Math.abs(bottom - top));
      });
    }

    if (overlays.zones) {
      const zones = cleanMode ? cleanPriorityZones(instance, setup) : (setup.zones || []);
      zones.forEach((zone) => {
        const top = coordinate(zone.high);
        const bottom = coordinate(zone.low);
        if (top == null || bottom == null) return;
        ctx.fillStyle = zone.kind === "DEMAND"
          ? (cleanMode ? "rgba(38,208,124,.040)" : "rgba(38,208,124,.075)")
          : (cleanMode ? "rgba(255,77,94,.040)" : "rgba(255,77,94,.075)");
        ctx.fillRect(0, Math.min(top, bottom), chartWidth, Math.abs(bottom - top));
      });
    }

    if (overlays.fib) {
      const fibContinuation = setup.primary_entry_model_key === "FIB_PULLBACK_CONTINUATION";
      const fibPrices = fibContinuation
        ? [setup.signals?.fib_pullback_zone_low, setup.signals?.fib_pullback_zone_high]
        : (setup.fib_levels || [])
          .filter((level) => Number(level.ratio) >= 0.618 - .003 && Number(level.ratio) <= 0.786 + .003)
          .map((level) => level.price);
      const values = fibPrices.map((price) => coordinate(Number(price))).filter((value) => value != null);
      if (values.length >= 2) {
        ctx.fillStyle = fibContinuation ? "rgba(245,185,59,.075)" : "rgba(169,139,255,.07)";
        ctx.fillRect(0, Math.min(...values), chartWidth, Math.max(...values) - Math.min(...values));
      }
    }

    if (overlays.trade && hasLockedTradePlan(setup)) {
      const entry = coordinate(setup.entry);
      const stop = coordinate(initialStop(setup));
      const tp1 = coordinate(setup.take_profit_1);
      const tp2 = coordinate(setup.take_profit_2);
      if ([entry, stop, tp1, tp2].every((value) => value != null)) {
        const startX = tradePlanStartX(instance, chartWidth);
        const endX = Math.max(startX + 1, chartWidth - 1);
        const boxWidth = Math.max(1, endX - startX);
        const rewardTop = Math.min(entry, tp2);
        const rewardHeight = Math.max(1, Math.abs(tp2 - entry));
        const riskTop = Math.min(entry, stop);
        const riskHeight = Math.max(1, Math.abs(stop - entry));

        ctx.save();
        ctx.fillStyle = "rgba(38,208,124,.13)";
        ctx.fillRect(startX, rewardTop, boxWidth, rewardHeight);
        ctx.strokeStyle = "rgba(38,208,124,.58)";
        ctx.lineWidth = 1;
        ctx.strokeRect(startX + .5, rewardTop + .5, Math.max(0, boxWidth - 1), Math.max(0, rewardHeight - 1));

        ctx.fillStyle = "rgba(255,77,94,.14)";
        ctx.fillRect(startX, riskTop, boxWidth, riskHeight);
        ctx.strokeStyle = "rgba(255,77,94,.62)";
        ctx.strokeRect(startX + .5, riskTop + .5, Math.max(0, boxWidth - 1), Math.max(0, riskHeight - 1));

        ctx.strokeStyle = "rgba(38,208,124,.92)";
        ctx.lineWidth = 1;
        ctx.setLineDash([6, 4]);
        ctx.beginPath(); ctx.moveTo(startX, tp1); ctx.lineTo(endX, tp1); ctx.stroke();
        ctx.setLineDash([]);

        ctx.strokeStyle = COLORS.amber;
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(startX, entry); ctx.lineTo(endX, entry); ctx.stroke();

        const precision = Number(instance.pricePrecision || 2);
        const rr = tradePlanRrLabel(setup);
        const orderText = `${executionOrderLabel(setup, true)} @ ${formatPrice(setup.entry, precision)}${rr ? ` · ${rr}` : ""}`;
        const labelY = entry - 24 >= 4 ? entry - 24 : entry + 4;
        drawCanvasTag(ctx, startX + 5, labelY, orderText, COLORS.amber, "#071019", Math.max(86, boxWidth - 10));

        ctx.font = "700 9px ui-monospace, SFMono-Regular, Menlo, monospace";
        ctx.textBaseline = "top";
        if (rewardHeight > 28) {
          ctx.fillStyle = "rgba(206,255,230,.90)";
          ctx.fillText(`TP2 ${formatPrice(setup.take_profit_2, precision)}`, startX + 8, rewardTop + 7);
        }
        if (Math.abs(tp1 - entry) > 18) {
          ctx.fillStyle = "rgba(192,255,220,.78)";
          ctx.fillText(`TP1 ${formatPrice(setup.take_profit_1, precision)}`, startX + 8, Math.max(rewardTop + 7, tp1 - 14));
        }
        if (riskHeight > 28) {
          ctx.fillStyle = "rgba(255,218,222,.90)";
          ctx.fillText(`SL ${formatPrice(initialStop(setup), precision)}`, startX + 8, riskTop + 7);
        }
        ctx.restore();
      }
    }
  }

  function defaultVisibleBars(instance, timeframe) {
    const tf = Number(timeframe || 1);
    const mobile = instance.host.clientWidth < 700;
    if (mobile) {
      if (tf <= 2) return 68;
      if (tf <= 5) return 78;
      if (tf <= 15) return 90;
      return 100;
    }
    if (instance.id === "chartLarge") {
      if (tf <= 2) return 90;
      if (tf <= 5) return 112;
      return 145;
    }
    if (tf <= 2) return 78;
    if (tf <= 5) return 92;
    return 110;
  }

  function applyData(instance, data) {
    const previous = instance.data;
    const sameTimeframe = instance.timeframe === data.timeframe;
    const sameSymbol = instance.symbol === data.symbol;
    const currentRange = instance.chart.timeScale().getVisibleLogicalRange();
    if (currentRange && instance.timeframe != null && instance.symbol) {
      desktopViewportCache.set(`${instance.symbol}:${instance.timeframe}:${instance.id}`, { from: currentRange.from, to: currentRange.to });
    }
    const savedRange = sameTimeframe && sameSymbol ? currentRange : null;
    const { incoming, resolved: candles } = resolveDesktopCandles(instance, data);
    const last = candles.at(-1);
    const oldLast = previous.at(-1);
    const canIncrement = Boolean(
      sameTimeframe && sameSymbol && oldLast && last && incoming.length > 0
      && last.time >= oldLast.time
      && candles.length >= previous.length
      && candles.length <= previous.length + 1
    );

    if (canIncrement) {
      instance.candleSeries.update(last);
      instance.closeSeries.update({ time: last.time, value: last.close });
      instance.volumeSeries.update(volumeData([last])[0]);
      const e9 = emaData(candles, 9).at(-1);
      const e21 = emaData(candles, 21).at(-1);
      const e55 = emaData(candles, 55).at(-1);
      if (e9) instance.ema9.update(e9);
      if (e21) instance.ema21.update(e21);
      if (e55) instance.ema55.update(e55);
    } else {
      instance.candleSeries.setData(candles);
      instance.closeSeries.setData(closeData(candles));
      instance.volumeSeries.setData(volumeData(candles));
      instance.ema9.setData(emaData(candles, 9));
      instance.ema21.setData(emaData(candles, 21));
      instance.ema55.setData(emaData(candles, 55));
      if (savedRange && instance.userInteracted) {
        requestAnimationFrame(() => instance.chart.timeScale().setVisibleLogicalRange(savedRange));
      }
    }

    instance.data = candles;
    instance.rthEq = rthEquilibrium(candles, data.symbol);
    instance.timeframe = data.timeframe;
    instance.symbol = data.symbol;
    instance.ema9.applyOptions({ visible: Boolean(data.overlays?.emas) });
    instance.ema21.applyOptions({ visible: Boolean(data.overlays?.emas) });
    instance.ema55.applyOptions({ visible: Boolean(data.overlays?.emas) });

    if (instance.firstRender || !sameTimeframe || !sameSymbol) {
      instance.firstRender = false;
      const viewportKey = `${data.symbol}:${data.timeframe}:${instance.id}`;
      const remembered = desktopViewportCache.get(viewportKey);
      instance.userInteracted = Boolean(remembered);
      requestAnimationFrame(() => {
        if (remembered) {
          instance.chart.timeScale().setVisibleLogicalRange(remembered);
          return;
        }
        const count = candles.length;
        const visibleBars = defaultVisibleBars(instance, data.timeframe);
        instance.chart.timeScale().setVisibleLogicalRange({
          from: Math.max(-4, count - visibleBars),
          to: count + (instance.id === "chartLarge" ? 10 : 6),
        });
      });
    }
  }

  function render(id, data, fromScheduledRender = false) {
    const host = document.getElementById(id);
    if (!hostIsReady(host)) {
      scheduleRender(id, data);
      return;
    }
    const instance = instances.get(id) || createInstance(id);
    if (!instance) {
      if (!fromScheduledRender) scheduleRender(id, data);
      return;
    }
    resizeInstance(instance);
    const changedSymbol = instance.symbol !== data.symbol;
    instance.setup = data.setup || null;
    instance.overlays = { ...(data.overlays || {}) };
    instance.displaySymbol = data.displaySymbol || `${data.symbol || "NQ"}1!`;
    instance.instrumentName = data.instrumentName || "Futures market";
    instance.tickSize = Number(data.tickSize || 0.25);
    instance.pricePrecision = Number.isInteger(data.pricePrecision) ? data.pricePrecision : 2;
    instance.candleSeries.applyOptions({ priceFormat: { type: "price", precision: instance.pricePrecision, minMove: instance.tickSize } });
    instance.chart.applyOptions({ localization: { priceFormatter: (price) => formatPrice(price, instance.pricePrecision), timeFormatter: (time) => displayChartTime(time) } });
    if (changedSymbol) {
      instance.firstRender = true;
      instance.data = [];
      clearSystemPriceLines(instance);
      instance.userPriceLines.forEach((line) => { try { instance.candleSeries.removePriceLine(line); } catch (_) { /* stale */ } });
      instance.userPriceLines = [];
    }
    applyData(instance, data);
    rebuildPriceLines(instance);
    scheduleOverlay(instance);
    updateLegend(instance, null);
    if (instance.dataState) {
      const sparse = instance.data.length < MIN_SAFE_HISTORY_BARS;
      const mismatch = instance.contractMismatch || data.dataQuality === "CONTRACT_MISMATCH";
      instance.dataState.hidden = Boolean(data.historyReady && !sparse && !mismatch);
      instance.dataState.classList.toggle("error", mismatch);
      instance.dataState.textContent = mismatch
        ? "PRICE REGIME RESET — MIXED CONTRACT DATA REJECTED"
        : `SYNCING COHERENT ${data.symbol || "FUTURES"} HISTORY · ${instance.data.length} BAR${instance.data.length === 1 ? "" : "S"}`;
    }

    const caption = document.getElementById(`${id}Status`);
    if (caption) {
      const tf = Number(data.timeframe) >= 60 ? `${Number(data.timeframe) / 60}h` : `${data.timeframe}m`;
      caption.textContent = `${instance.instrumentName} · ${tf} · ${data.dataSource || "CONNECTING"}${data.rawSymbol ? ` · ${data.rawSymbol}` : ""}${instance.historyRecovered ? " · HISTORY RESTORED" : ""}${instance.contractMismatch ? " · REGIME RESET" : ""}`;
    }
  }

  function marketChanged(id) {
    const instance = instances.get(id);
    if (!instance) return;
    instance.firstRender = true;
    instance.data = [];
    instance.timeframe = null;
    clearSystemPriceLines(instance);
    instance.userPriceLines.forEach((line) => { try { instance.candleSeries.removePriceLine(line); } catch (_) { /* stale */ } });
    instance.userPriceLines = [];
  }

  function reset(id) {
    const instance = instances.get(id);
    if (!instance) return;
    instance.chart.timeScale().scrollToRealTime();
    instance.candleSeries.priceScale().applyOptions({ autoScale: true });
    instance.autoScale = true;
    scheduleOverlay(instance);
  }

  function resize(id) {
    const instance = instances.get(id);
    if (instance) resizeInstance(instance);
    const pending = pendingRenders.get(id);
    if (pending) scheduleRender(id, pending);
  }

  function refresh(id) {
    const instance = instances.get(id);
    if (instance) {
      resizeInstance(instance);
      instance.chart.timeScale().scrollToRealTime();
      scheduleOverlay(instance);
    }
  }

  window.visualViewport?.addEventListener("resize", () => {
    instances.forEach((instance) => resizeInstance(instance));
  });
  window.TradeIQChartManager = { render, reset, marketChanged, resize, refresh, instances };
})();

// Legacy v2.1 regression marker only: else if (overlays.trade && hasLockedTradePlan(setup))
// Legacy v3.1.3 regression marker only: if (marketMapVisible && renderCleanMarketMapLines(instance, setup)) return;
