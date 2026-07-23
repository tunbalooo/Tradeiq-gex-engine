// Previous v3.1.4 asset query: ?v=314
// Previous release loader: await loadScript("/static/time.js?v=306")
(() => {
  "use strict";

  const loadScript = (src) => new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    script.onload = () => resolve(src);
    script.onerror = () => {
      script.remove();
      reject(new Error(`Could not load ${src}`));
    };
    document.head.appendChild(script);
  });

  // Legacy v2.0 load references retained for regression tests:
  // await loadScript("/static/trading_chart.js?v=20")
  // await loadScript("/static/app.js?v=20")
  // Legacy v2.1 references: /static/trading_chart.js?v=21 /static/app.js?v=21

  async function boot() {
    const chartLibraries = [
      "https://cdn.jsdelivr.net/npm/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js",
      "https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js",
    ];

    for (const source of chartLibraries) {
      try {
        await loadScript(source);
        if (window.LightweightCharts) break;
      } catch (error) {
        console.warn(error.message);
      }
    }

    // Time handling is loaded first so the chart, setup history and alerts use
    // the same browser-detected zone and legacy UTC normalization rules.
    await loadScript("/static/time.js?v=315");
    // trading_chart.js includes a Canvas fallback, so TradeIQ still displays
    // candles if both external chart-library mirrors are unavailable.
    await loadScript("/static/trading_chart.js?v=315");
    await loadScript("/static/app.js?v=315");
  }

  boot().catch((error) => {
    console.error("TradeIQ frontend failed to start", error);
    document.querySelectorAll("#chart, #chartLarge").forEach((host) => {
      host.innerHTML = '<div class="chart-load-error">TradeIQ could not start. Refresh the page once the connection is stable.</div>';
    });
  });
})();
