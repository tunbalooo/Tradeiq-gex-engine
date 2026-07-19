const CACHE_NAME = "tradeiq-v1.9-shell";
const APP_SHELL = [
  "/",
  "/static/styles.css?v=19",
  "/static/boot.js?v=19",
  "/static/app.js?v=19",
  "/static/trading_chart.js?v=19",
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
