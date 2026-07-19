(() => {
  "use strict";

  const LC = window.LightweightCharts;
  const USE_MOBILE_CANVAS = window.matchMedia?.("(max-width: 900px)")?.matches === true;

  function installCanvasFallback() {
    console.warn("Lightweight Charts was unavailable; TradeIQ is using its built-in Canvas chart fallback.");
    const fallbackInstances = new Map();
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
      canvas.setAttribute("aria-label", "TradeIQ fallback candlestick chart");
      host.appendChild(canvas);
      instance = { id, host, canvas, payload: null, visibleCount: id === "chartLarge" ? 88 : 72, offset: 0, chartStyle: "candles", dragging: false, dragX: 0, dragOffset: 0 };
      fallbackInstances.set(id, instance);
      const observer = new ResizeObserver(() => drawFallback(instance));
      observer.observe(host);
      instance.resizeObserver = observer;
      bindFallbackControls(instance);
      bindFallbackGestures(instance);
      return instance;
    }

    function clamp(value, minimum, maximum) { return Math.max(minimum, Math.min(maximum, value)); }

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
          if (["recenter", "fit"].includes(action)) instance.offset = 0;
          if (action === "fit") instance.visibleCount = instance.id === "chartLarge" ? 88 : 72;
          if (action === "candles") instance.chartStyle = "candles";
          if (action === "line") instance.chartStyle = "line";
          if (action === "fullscreen") {
            const root = instance.host.closest(".tv-full-panel") || instance.host.closest(".tv-workstation") || instance.host;
            if (document.fullscreenElement) document.exitFullscreen?.(); else root.requestFullscreen?.();
          }
          drawFallback(instance);
        });
      });
    }

    function bindFallbackGestures(instance) {
      const canvas = instance.canvas;
      canvas.addEventListener("pointerdown", (event) => {
        instance.dragging = true; instance.dragX = event.clientX; instance.dragOffset = instance.offset;
        canvas.setPointerCapture?.(event.pointerId);
      });
      canvas.addEventListener("pointermove", (event) => {
        if (!instance.dragging) return;
        const candles = instance.payload?.candles?.length || 0;
        const pixelsPerBar = Math.max(3, canvas.clientWidth / Math.max(instance.visibleCount, 1));
        const shift = Math.round((event.clientX - instance.dragX) / pixelsPerBar);
        instance.offset = clamp(instance.dragOffset + shift, 0, Math.max(0, candles - 10));
        drawFallback(instance);
      });
      const stop = () => { instance.dragging = false; };
      canvas.addEventListener("pointerup", stop); canvas.addEventListener("pointercancel", stop);
      canvas.addEventListener("wheel", (event) => {
        event.preventDefault();
        instance.visibleCount = clamp(Math.round(instance.visibleCount * (event.deltaY < 0 ? .88 : 1.12)), 24, 180);
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
      const candles = raw.map((item) => ({
        time: fallbackTime(item.time), open: Number(item.open), high: Number(item.high),
        low: Number(item.low), close: Number(item.close), volume: Number(item.volume || 0),
      })).filter((item) => item.time != null && [item.open, item.high, item.low, item.close].every(Number.isFinite));
      if (!candles.length) {
        ctx.fillStyle = "#7788A3";
        ctx.font = "500 12px ui-monospace, monospace";
        ctx.textAlign = "center";
        ctx.fillText("Waiting for market candles…", width / 2, height / 2);
        return;
      }

      const visibleCount = Math.min(candles.length, instance.visibleCount || (instance.id === "chartLarge" ? 88 : 72));
      const end = Math.max(1, candles.length - Math.max(0, instance.offset || 0));
      const start = Math.max(0, end - visibleCount);
      const values = candles.slice(start, end);
      const setupForScale = payload?.setup || {};
      const extra = [setupForScale.entry, setupForScale.stop_loss, setupForScale.take_profit_1, setupForScale.take_profit_2,
        setupForScale.vwap, setupForScale.standard_deviation_high, setupForScale.standard_deviation_low,
        setupForScale.gex?.call_wall, setupForScale.gex?.gamma_flip, setupForScale.gex?.put_wall]
        .map(Number).filter(Number.isFinite);
      let low = Math.min(...values.map((item) => item.low), ...extra);
      let high = Math.max(...values.map((item) => item.high), ...extra);
      const pad = Math.max((high - low) * 0.08, Number(payload?.tickSize || 0.25) * 8);
      low -= pad; high += pad;
      const plotRight = width - 58;
      const plotTop = 16;
      const volumeHeight = Math.max(34, Math.min(60, height * .14));
      const plotBottom = height - volumeHeight - 28;
      const plotHeight = Math.max(1, plotBottom - plotTop);
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

      if (overlays.zones) {
        (setup.zones || []).slice(0, 4).forEach((zone) => {
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
        horizontal(ctx, toY(setup.gex.call_wall), plotRight, "CALL", lineColors.gex);
        horizontal(ctx, toY(setup.gex.gamma_flip), plotRight, "γ FLIP", lineColors.entry);
        horizontal(ctx, toY(setup.gex.put_wall), plotRight, "PUT", lineColors.stop);
      }
      if (overlays.vwap) horizontal(ctx, toY(setup.vwap), plotRight, "VWAP", lineColors.vwap, false);
      if (overlays.trade && setup.entry != null) {
        horizontal(ctx, toY(setup.entry), plotRight, setup.order_state === "PREVIEW_ONLY" ? "WATCH" : "ENTRY", lineColors.entry, false);
        horizontal(ctx, toY(setup.stop_loss), plotRight, "SL", lineColors.stop, false);
        horizontal(ctx, toY(setup.take_profit_1), plotRight, "TP1", lineColors.target);
        horizontal(ctx, toY(setup.take_profit_2), plotRight, "TP2", lineColors.target, false);
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
    }

    function render(id, data) {
      const instance = ensureFallback(id);
      if (!instance) return;
      const marketChanged = instance.payload && (instance.payload.symbol !== data.symbol || instance.payload.timeframe !== data.timeframe);
      instance.payload = data;
      if (marketChanged) instance.offset = 0;
      requestAnimationFrame(() => drawFallback(instance));
    }
    function reset(id) {
      const instance = fallbackInstances.get(id);
      if (instance) { instance.offset = 0; instance.visibleCount = id === "chartLarge" ? 88 : 72; drawFallback(instance); }
    }
    function marketChanged(id) { const instance = fallbackInstances.get(id); if (instance) { instance.payload = null; drawFallback(instance); } }
    function resize(id) { const instance = fallbackInstances.get(id); if (instance) drawFallback(instance); }
    function refresh(id) { const instance = fallbackInstances.get(id); if (instance) drawFallback(instance); }
    window.TradeIQChartManager = { render, reset, marketChanged, resize, refresh, instances: fallbackInstances, fallback: true, mobileCanvas: USE_MOBILE_CANVAS };
  }

  if (!LC || USE_MOBILE_CANVAS) {
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
  const pendingRenders = new Map();
  const renderTimers = new Map();
  const dashed = LC.LineStyle?.Dashed ?? 2;
  const dotted = LC.LineStyle?.Dotted ?? 1;

  function unixTime(value) {
    const timestamp = Math.floor(new Date(value).getTime() / 1000);
    return Number.isFinite(timestamp) ? timestamp : null;
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
      };
      if (Object.values(item).slice(1).every(Number.isFinite)) byTime.set(time, item);
    });
    return [...byTime.values()].sort((a, b) => a.time - b.time);
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

  function formatPrice(value, precision = 2) {
    if (!Number.isFinite(Number(value))) return "—";
    return Number(value).toLocaleString("en-US", {
      minimumFractionDigits: precision,
      maximumFractionDigits: precision,
    });
  }

  function etTime(time) {
    if (!time) return "—";
    return new Date(Number(time) * 1000).toLocaleString("en-US", {
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
      instance.chart.resize(width, height);
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
        minimumWidth: 76,
        scaleMargins: { top: 0.09, bottom: 0.12 },
        ticksVisible: true,
      },
      leftPriceScale: { visible: false },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: id === "chartLarge" ? 12 : 8,
        barSpacing: id === "chartLarge" ? 8 : 6,
        minBarSpacing: 0.45,
        maxBarSpacing: 42,
        lockVisibleTimeRangeOnResize: true,
        rightBarStaysOnScroll: true,
        shiftVisibleRangeOnNewBar: true,
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
      localization: {
        priceFormatter: (price) => formatPrice(price),
        timeFormatter: (time) => etTime(time),
      },
    });

    const candleSeries = chart.addSeries(LC.CandlestickSeries, {
      upColor: COLORS.green,
      downColor: COLORS.red,
      borderVisible: false,
      wickUpColor: COLORS.green,
      wickDownColor: COLORS.red,
      priceLineVisible: true,
      lastValueVisible: true,
      priceFormat: { type: "price", precision: 2, minMove: 0.25 },
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

    const overlayCanvas = document.createElement("canvas");
    overlayCanvas.className = "tv-overlay-canvas";
    overlayCanvas.setAttribute("aria-hidden", "true");
    host.appendChild(overlayCanvas);

    const instance = {
      id,
      host,
      chart,
      candleSeries,
      closeSeries,
      ema9,
      ema21,
      ema55,
      overlayCanvas,
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
      lastWidth: initialSize.width,
      lastHeight: initialSize.height,
    };

    chart.subscribeCrosshairMove((param) => updateLegend(instance, param));
    chart.subscribeClick((param) => handleChartClick(instance, param));
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => scheduleOverlay(instance));

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
      case "recenter": instance.chart.timeScale().scrollToRealTime(); instance.candleSeries.priceScale().applyOptions({ autoScale: true }); break;
      case "fit": instance.chart.timeScale().fitContent(); instance.candleSeries.priceScale().applyOptions({ autoScale: true }); break;
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
    if (document.fullscreenElement) document.exitFullscreen?.();
    else root.requestFullscreen?.();
  }

  function clearSystemPriceLines(instance) {
    instance.priceLines.forEach((line) => {
      try { instance.candleSeries.removePriceLine(line); } catch (_) { /* stale line */ }
    });
    instance.priceLines = [];
  }

  function addPriceLine(instance, price, title, color, style = dashed, width = 1) {
    if (!Number.isFinite(Number(price))) return;
    const line = instance.candleSeries.createPriceLine({
      price: Number(price), color, lineWidth: width, lineStyle: style,
      axisLabelVisible: true, title,
    });
    instance.priceLines.push(line);
  }

  function rebuildPriceLines(instance) {
    clearSystemPriceLines(instance);
    const setup = instance.setup;
    const overlays = instance.overlays || {};
    if (!setup) return;

    if (overlays.gex && setup.gex) {
      addPriceLine(instance, setup.gex.call_wall, "CALL WALL", COLORS.blue, dashed, 2);
      addPriceLine(instance, setup.gex.gamma_flip, "γ FLIP", COLORS.amber, dashed, 2);
      addPriceLine(instance, setup.gex.put_wall, "PUT WALL", COLORS.red, dashed, 2);
      (setup.gex.levels || []).slice(0, instance.id === "chartLarge" ? 6 : 3).forEach((level) => {
        addPriceLine(instance, level.price, level.type || "GEX", Number(level.gex || 0) >= 0 ? "#21875A" : "#9D3542", dotted, 1);
      });
    }

    if (overlays.fib) {
      (setup.fib_levels || []).forEach((level) => {
        addPriceLine(instance, level.price, level.label || String(level.ratio), Math.abs(Number(level.ratio) - 0.705) < 0.002 ? COLORS.amber : "#49576A", dotted, 1);
      });
    }

    if (overlays.vwap) {
      addPriceLine(instance, setup.vwap, "VWAP", COLORS.vwap, dotted, 1);
      addPriceLine(instance, setup.standard_deviation_high, "+1σ", COLORS.muted, dotted, 1);
      addPriceLine(instance, setup.standard_deviation_low, "-1σ", COLORS.muted, dotted, 1);
    }

    if (overlays.trade && setup.entry != null) {
      const preview = setup.order_state === "PREVIEW_ONLY";
      addPriceLine(instance, setup.entry, preview ? "WATCH" : "ENTRY", COLORS.amber, preview ? dotted : dashed, 2);
      addPriceLine(instance, setup.stop_loss, "SL", COLORS.red, dashed, 2);
      addPriceLine(instance, setup.take_profit_1, "TP1", COLORS.green, dashed, 2);
      addPriceLine(instance, setup.take_profit_2, "TP2", COLORS.green, dashed, 2);
    }

    if (overlays.zones) {
      (setup.zones || []).slice(0, instance.id === "chartLarge" ? 7 : 4).forEach((zone) => {
        const color = zone.kind === "DEMAND" ? "#21875A" : "#9D3542";
        addPriceLine(instance, zone.high, `${zone.timeframe} ${zone.kind}`, color, dotted, 1);
        addPriceLine(instance, zone.low, "", color, dotted, 1);
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
    if (!setup) return;
    const chartWidth = Math.max(0, width - 77);
    const coordinate = (price) => instance.candleSeries.priceToCoordinate(Number(price));

    if (overlays.zones) {
      (setup.zones || []).slice(0, instance.id === "chartLarge" ? 9 : 5).forEach((zone) => {
        const top = coordinate(zone.high);
        const bottom = coordinate(zone.low);
        if (top == null || bottom == null) return;
        ctx.fillStyle = zone.kind === "DEMAND" ? "rgba(38,208,124,.075)" : "rgba(255,77,94,.075)";
        ctx.fillRect(0, Math.min(top, bottom), chartWidth, Math.abs(bottom - top));
      });
    }

    if (overlays.fib) {
      const ote = (setup.fib_levels || []).filter((level) => Number(level.ratio) >= 0.618 && Number(level.ratio) <= 0.786);
      if (ote.length) {
        const values = ote.map((level) => coordinate(level.price)).filter((value) => value != null);
        if (values.length) {
          ctx.fillStyle = "rgba(169,139,255,.07)";
          ctx.fillRect(0, Math.min(...values), chartWidth, Math.max(...values) - Math.min(...values));
        }
      }
    }

    if (overlays.trade && setup.entry != null) {
      const entry = coordinate(setup.entry);
      const stop = coordinate(setup.stop_loss);
      const target = coordinate(setup.take_profit_2);
      if (entry != null && stop != null && target != null) {
        const startX = chartWidth * (instance.id === "chartLarge" ? 0.68 : 0.72);
        ctx.fillStyle = "rgba(38,208,124,.07)";
        ctx.fillRect(startX, Math.min(entry, target), chartWidth - startX, Math.abs(target - entry));
        ctx.fillStyle = "rgba(255,77,94,.08)";
        ctx.fillRect(startX, Math.min(entry, stop), chartWidth - startX, Math.abs(stop - entry));
      }
    }
  }

  function applyData(instance, data) {
    const previous = instance.data;
    const sameTimeframe = instance.timeframe === data.timeframe;
    const sameSymbol = instance.symbol === data.symbol;
    const candles = normaliseCandles(data.candles);
    const last = candles.at(-1);
    const oldLast = previous.at(-1);
    const canIncrement = sameTimeframe && sameSymbol && oldLast && last && candles.length >= previous.length && candles.length <= previous.length + 1;

    if (canIncrement) {
      instance.candleSeries.update(last);
      instance.closeSeries.update({ time: last.time, value: last.close });
      const e9 = emaData(candles, 9).at(-1);
      const e21 = emaData(candles, 21).at(-1);
      const e55 = emaData(candles, 55).at(-1);
      if (e9) instance.ema9.update(e9);
      if (e21) instance.ema21.update(e21);
      if (e55) instance.ema55.update(e55);
    } else {
      instance.candleSeries.setData(candles);
      instance.closeSeries.setData(closeData(candles));
      instance.ema9.setData(emaData(candles, 9));
      instance.ema21.setData(emaData(candles, 21));
      instance.ema55.setData(emaData(candles, 55));
    }

    instance.data = candles;
    instance.timeframe = data.timeframe;
    instance.symbol = data.symbol;
    instance.ema9.applyOptions({ visible: Boolean(data.overlays?.emas) });
    instance.ema21.applyOptions({ visible: Boolean(data.overlays?.emas) });
    instance.ema55.applyOptions({ visible: Boolean(data.overlays?.emas) });

    if (instance.firstRender || !sameTimeframe || !sameSymbol) {
      instance.firstRender = false;
      requestAnimationFrame(() => {
        const count = candles.length;
        const visibleBars = instance.id === "chartLarge" ? 170 : 115;
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
    instance.chart.applyOptions({ localization: { priceFormatter: (price) => formatPrice(price, instance.pricePrecision), timeFormatter: (time) => etTime(time) } });
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

    const caption = document.getElementById(`${id}Status`);
    if (caption) {
      const tf = Number(data.timeframe) >= 60 ? `${Number(data.timeframe) / 60}h` : `${data.timeframe}m`;
      caption.textContent = `${instance.instrumentName} · ${tf} · ${data.dataSource || "CONNECTING"}`;
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

  window.TradeIQChartManager = { render, reset, marketChanged, resize, refresh, instances };
})();
