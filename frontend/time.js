(() => {
  "use strict";

  const STORAGE_KEY = "tradeiq-display-time-zone";
  const EXCHANGE_ZONE = "America/New_York";
  const detectedZone = (() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || EXCHANGE_ZONE;
    } catch (_error) {
      return EXCHANGE_ZONE;
    }
  })();

  function preference() {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "EXCHANGE" ? "EXCHANGE" : "AUTO";
  }

  function zone() {
    return preference() === "EXCHANGE" ? EXCHANGE_ZONE : detectedZone;
  }

  function setPreference(value) {
    const resolved = value === "EXCHANGE" ? "EXCHANGE" : "AUTO";
    localStorage.setItem(STORAGE_KEY, resolved);
    window.dispatchEvent(new CustomEvent("tradeiq-timezone-change", {
      detail: { preference: resolved, zone: zone() },
    }));
    return resolved;
  }

  function normalize(value) {
    if (value == null || value === "") return null;
    if (value instanceof Date) return value;
    if (typeof value === "number") {
      const milliseconds = Math.abs(value) < 1e12 ? value * 1000 : value;
      const date = new Date(milliseconds);
      return Number.isNaN(date.getTime()) ? null : date;
    }
    const text = String(value).trim();
    if (!text) return null;
    // Legacy SQLite responses omitted the UTC offset even though TradeIQ stored
    // those values in UTC. Treat offset-less API timestamps as UTC so old setup
    // history rows remain correct after this release.
    const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text);
    const normalized = hasOffset ? text : `${text}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function parts(value = new Date(), options = {}) {
    const date = normalize(value) || new Date();
    try {
      return new Intl.DateTimeFormat("en-US", {
        timeZone: zone(),
        ...options,
      }).formatToParts(date);
    } catch (_error) {
      return new Intl.DateTimeFormat("en-US", options).formatToParts(date);
    }
  }

  function format(value, options = {}) {
    const date = normalize(value);
    if (!date) return "—";
    try {
      return new Intl.DateTimeFormat("en-US", {
        timeZone: zone(),
        ...options,
      }).format(date);
    } catch (_error) {
      return date.toLocaleString("en-US", options);
    }
  }

  function abbreviation(value = new Date()) {
    const token = parts(value, { timeZoneName: "short" }).find((item) => item.type === "timeZoneName");
    return token?.value || zone();
  }

  function formatTime(value, options = {}) {
    return format(value, {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      ...options,
    });
  }

  function formatDateTime(value, options = {}) {
    return format(value, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
      ...options,
    });
  }

  function formatChartTime(value) {
    return format(value, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function nowClock() {
    const tokens = Object.fromEntries(parts(new Date(), {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZoneName: "short",
    }).map((item) => [item.type, item.value]));
    return `${tokens.hour || "--"}:${tokens.minute || "--"}:${tokens.second || "--"} ${tokens.timeZoneName || abbreviation()}`;
  }

  window.TradeIQTime = Object.freeze({
    detectedZone,
    exchangeZone: EXCHANGE_ZONE,
    preference,
    zone,
    setPreference,
    normalize,
    format,
    formatTime,
    formatDateTime,
    formatChartTime,
    abbreviation,
    nowClock,
  });
})();
