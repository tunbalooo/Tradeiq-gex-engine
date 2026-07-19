(() => {
  "use strict";

  const LC = window.LightweightCharts;
  if (!LC) {
    console.error("Lightweight Charts failed to load; interactive chart is unavailable.");
    document.querySelectorAll("#chart, #chartLarge").forEach((host) => {
      host.innerHTML = '<div class="chart-load-error">Interactive chart library could not load. Refresh the page or check the browser network connection.</div>';
    });
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

  function createInstance(id) {
    const host = document.getElementById(id);
    if (!host) return null;

    const chart = LC.createChart(host, {
      autoSize: true,
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
    };

    chart.subscribeCrosshairMove((param) => updateLegend(instance, param));
    chart.subscribeClick((param) => handleChartClick(instance, param));
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => scheduleOverlay(instance));

    const resizeObserver = new ResizeObserver(() => scheduleOverlay(instance));
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

  function render(id, data) {
    const instance = instances.get(id) || createInstance(id);
    if (!instance) return;
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

  window.TradeIQChartManager = { render, reset, marketChanged, instances };
})();
