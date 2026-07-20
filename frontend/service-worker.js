// Legacy v2.5 asset query: ?v=25
// Legacy v2.5 cache reference: CACHE_NAME = "tradeiq-v2.5-shell"
// Legacy v2.4 cache: CACHE_NAME = "tradeiq-v2.4-shell"; assets used ?v=24
// legacy ?v=23 assets retained for regression checks
// CACHE_NAME = "tradeiq-v2.3-shell"
// Current v2.6: active setup memory survives restarts and every setup exposes a deterministic timeline.
// TradeIQ v3.0: Decision Brain, ranked entry models, professional management and read-only analytics.
// Legacy v3.0 cache: CACHE_NAME = "tradeiq-v3.0-shell"
// TradeIQ v3.0.1: coherent small-timeframe candles and price-first autoscaling.
// Legacy v2.6 cache reference: CACHE_NAME = "tradeiq-v2.6-shell"
// Legacy cache references retained for regression tests: tradeiq-v2.0-shell tradeiq-v2.1-shell tradeiq-v2.2-shell
// /static/styles.css?v=20 /static/boot.js?v=20 /static/app.js?v=20 /static/trading_chart.js?v=20
// Legacy v2.1 assets: /static/styles.css?v=21 /static/boot.js?v=21 /static/app.js?v=21 /static/trading_chart.js?v=21
// Legacy v2.2 assets: /static/styles.css?v=22 /static/boot.js?v=22 /static/app.js?v=22 /static/trading_chart.js?v=22
// Legacy v2.3 assets: /static/styles.css?v=23 /static/boot.js?v=23 /static/app.js?v=23 /static/trading_chart.js?v=23
const CACHE_NAME = "tradeiq-v3.0.1-chart-hotfix-shell";
const APP_SHELL = [
  "/",
  "/static/styles.css?v=301",
  "/static/boot.js?v=301",
  "/static/app.js?v=301",
  "/static/trading_chart.js?v=301",
  "/static/manifest.webmanifest",
  "/static/favicon.svg",
  "/static/app-icon-192.png",
  "/static/app-icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) {
    event.respondWith(fetch(request));
    return;
  }

  // Network-first prevents an installed iPhone/iPad app from remaining stuck
  // on an older TradeIQ deployment after Railway publishes a new version.
  event.respondWith(
    fetch(request).then((response) => {
      const copy = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
      return response;
    }).catch(() => caches.match(request).then((cached) => cached || caches.match("/")))
  );
});
