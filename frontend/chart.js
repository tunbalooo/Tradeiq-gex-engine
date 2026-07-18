/*
 * TradeIQ chart — TradingView-style candles via Lightweight Charts.
 * Native pan / scroll-zoom / crosshair / auto price-scale, plus every
 * TradeIQ overlay (EMAs, GEX walls, fib/OTE, S&D zones, entry/SL/TP,
 * VWAP/σ) drawn on top and wired to the existing state.overlays toggles.
 *
 * Exposes window.TradeIQChart with:
 *   init(container)            -> build the chart once
 *   setCandles(candles)        -> replace the candle series data
 *   updateLast(candle)         -> live-update the most recent bar
 *   renderOverlays(setup, on)  -> redraw overlays for a setup + toggle map
 *   fit()                      -> reset zoom to fit content
 *   resize()                   -> handle container resize
 */
(function () {
  const C = {
    green: "#26D07C", red: "#FF4D5E", amber: "#F5B93B", blue: "#48A3FF",
    purple: "#A98BFF", muted: "#6E7F97", grid: "rgba(255,255,255,.04)",
    text: "#D8E2F0", bg: "#0C121C",
  };

  let chart = null;
  let candleSeries = null;
  let emaSeries = {};        // {9,21,55} line series
  let priceLines = [];       // horizontal GEX/fib/trade/vwap lines
  let zoneSeries = [];       // area series used as shaded S&D/OTE bands
  let lastCandles = [];

  function toBar(c) {
    // Lightweight Charts wants UNIX seconds for intraday time.
    return {
      time: Math.floor(new Date(c.time).getTime() / 1000),
      open: c.open, high: c.high, low: c.low, close: c.close,
    };
  }

  function ema(candles, period) {
    if (!candles.length) return [];
    const a = 2 / (period + 1);
    let v = candles[0].close;
    return candles.map((c) => {
      v = c.close * a + v * (1 - a);
      return { time: Math.floor(new Date(c.time).getTime() / 1000), value: v };
    });
  }

  function init(container) {
    if (chart) return;
    chart = LightweightCharts.createChart(container, {
      layout: { background: { color: "transparent" }, textColor: C.muted, fontFamily: "ui-monospace, monospace" },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: "#1A2636", scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: "#1A2636", timeVisible: true, secondsVisible: false, rightOffset: 6 },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: "#3A4658", labelBackgroundColor: "#1A2636" },
        horzLine: { color: "#3A4658", labelBackgroundColor: "#1A2636" },
      },
      handleScroll: {
        mouseWheel: true, pressedMouseMove: true,
        horzTouchDrag: true, vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: true, mouseWheel: true, pinch: true,
      },
      kineticScroll: { touch: true, mouse: false },
      autoSize: true,
    });

    candleSeries = chart.addCandlestickSeries({
      upColor: C.green, downColor: C.red, borderUpColor: C.green, borderDownColor: C.red,
      wickUpColor: C.green, wickDownColor: C.red, priceLineColor: "#5B718C",
    });

    emaSeries = {
      9: chart.addLineSeries({ color: C.amber, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }),
      21: chart.addLineSeries({ color: C.blue, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }),
      55: chart.addLineSeries({ color: C.purple, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }),
    };

    addNavButtons(container);
  }

  function addNavButtons(container) {
    const ts = () => chart.timeScale();
    const bar = document.createElement("div");
    bar.className = "chart-nav";
    const mk = (label, title, fn) => {
      const b = document.createElement("button");
      b.textContent = label; b.title = title; b.type = "button";
      b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
      bar.appendChild(b); return b;
    };
    const shift = (bars) => {
      const r = ts().getVisibleLogicalRange();
      if (r) ts().setVisibleLogicalRange({ from: r.from + bars, to: r.to + bars });
    };
    const zoom = (factor) => {
      const r = ts().getVisibleLogicalRange();
      if (!r) return;
      const mid = (r.from + r.to) / 2, half = (r.to - r.from) * factor / 2;
      ts().setVisibleLogicalRange({ from: mid - half, to: mid + half });
    };
    mk("−", "Zoom out", () => zoom(1.25));
    mk("+", "Zoom in", () => zoom(0.8));
    mk("‹", "Scroll back", () => shift(-12));
    mk("›", "Scroll forward", () => shift(12));
    mk("⟲", "Reset to latest", () => { ts().scrollToRealTime(); ts().fitContent(); });
    container.style.position = "relative";
    container.appendChild(bar);
  }

  function setCandles(candles) {
    if (!candleSeries) return;
    lastCandles = candles;
    candleSeries.setData(candles.map(toBar));
    Object.entries(emaSeries).forEach(([p, s]) => s.setData(ema(candles, Number(p))));
  }

  function updateLast(candle) {
    if (!candleSeries || !candle) return;
    candleSeries.update(toBar(candle));
    // EMAs recompute cheaply off the in-memory series; refresh last point.
    if (lastCandles.length) {
      const merged = [...lastCandles];
      const t = new Date(candle.time).getTime();
      const lastT = new Date(merged[merged.length - 1].time).getTime();
      if (t === lastT) merged[merged.length - 1] = candle; else merged.push(candle);
      lastCandles = merged.slice(-1400);
      Object.entries(emaSeries).forEach(([p, s]) => {
        const series = ema(lastCandles, Number(p));
        if (series.length) s.update(series[series.length - 1]);
      });
    }
  }

  function clearOverlays() {
    priceLines.forEach((l) => candleSeries.removePriceLine(l));
    priceLines = [];
    zoneSeries.forEach((s) => chart.removeSeries(s));
    zoneSeries = [];
  }

  function hline(price, title, color, style = 0, width = 1) {
    if (!Number.isFinite(Number(price))) return;
    priceLines.push(candleSeries.createPriceLine({
      price: Number(price), color, lineWidth: width, lineStyle: style,
      axisLabelVisible: true, title,
    }));
  }

  // Shaded horizontal band between two prices, spanning the visible range.
  function band(low, high, color) {
    if (!Number.isFinite(low) || !Number.isFinite(high) || !lastCandles.length) return;
    const t0 = Math.floor(new Date(lastCandles[0].time).getTime() / 1000);
    const t1 = Math.floor(new Date(lastCandles[lastCandles.length - 1].time).getTime() / 1000) + 6 * 3600;
    const top = chart.addAreaSeries({
      topColor: color, bottomColor: color, lineColor: "rgba(0,0,0,0)",
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    // Area fills from the line down to `high` baseline; emulate a band by
    // drawing the high edge and baselining at low.
    top.setData([{ time: t0, value: high }, { time: t1, value: high }]);
    top.applyOptions({ baseLineVisible: false, priceScaleId: candleSeries.priceScale().id });
    // Second area for the lower edge keeps the fill bounded visually.
    zoneSeries.push(top);
  }

  const STYLE = { solid: 0, dotted: 1, dashed: 2, largeDashed: 3, sparseDotted: 4 };

  function renderOverlays(setup, on) {
    if (!chart || !candleSeries || !setup) return;
    clearOverlays();

    // EMAs
    const vis = on.emas;
    Object.values(emaSeries).forEach((s) => s.applyOptions({ visible: vis }));

    // S&D zones as shaded bands
    if (on.zones && setup.zones) {
      setup.zones.slice(0, 8).forEach((z) => {
        const col = z.kind === "DEMAND" ? "rgba(38,208,124,.10)" : "rgba(255,77,94,.10)";
        band(z.low, z.high, col);
      });
    }

    // Fib / OTE
    if (on.fib && setup.fib_levels) {
      const ote = setup.fib_levels.filter((l) => l.ratio >= 0.618 && l.ratio <= 0.786).map((l) => l.price);
      if (ote.length) band(Math.min(...ote), Math.max(...ote), "rgba(169,139,255,.10)");
      setup.fib_levels.forEach((l) =>
        hline(l.price, l.ratio.toFixed(3), Math.abs(l.ratio - 0.705) < 0.002 ? C.amber : "#3A4658", STYLE.dotted));
    }

    // GEX walls
    if (on.gex) {
      hline(setup.gex.call_wall, "CALL WALL", C.blue, STYLE.dashed, 2);
      hline(setup.gex.gamma_flip, "γ FLIP", C.amber, STYLE.dashed, 2);
      hline(setup.gex.put_wall, "PUT WALL", C.red, STYLE.dashed, 2);
    }

    // VWAP / σ
    if (on.vwap) {
      hline(setup.vwap, "VWAP", "#E4D06F", STYLE.dotted);
      hline(setup.standard_deviation_high, "+1σ", "#5B718C", STYLE.sparseDotted);
      hline(setup.standard_deviation_low, "-1σ", "#5B718C", STYLE.sparseDotted);
    }

    // Trade plan
    if (on.trade && setup.entry != null) {
      hline(setup.entry, "LIMIT", C.amber, STYLE.solid, 1);
      hline(setup.stop_loss, "SL", C.red, STYLE.solid, 1);
      hline(setup.take_profit_1, "TP1", C.green, STYLE.dashed, 1);
      hline(setup.take_profit_2, "TP2", C.green, STYLE.solid, 1);
    }
  }

  function fit() { if (chart) chart.timeScale().fitContent(); }
  function resize() { if (chart) chart.applyOptions({ autoSize: true }); }

  window.TradeIQChart = { init, setCandles, updateLast, renderOverlays, fit, resize };
})();
