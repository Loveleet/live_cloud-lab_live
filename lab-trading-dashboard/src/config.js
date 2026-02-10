/** Cloud API (direct IP). Use tunnel URL in .env.local if this isn't reachable from your network. */
const CLOUD_API = "http://150.241.244.130:10000";

/** Set by runtime config (api-config.json) when loaded — so GitHub Pages keeps working after cloud reboot */
let runtimeApiBaseUrl = null;
let loggedEmptyOnce = false;
let fetchLoggedOnce = false;

/**
 * Build-time default (env or cloud IP). On HTTPS we never use raw IP (no valid cert → ERR_SSL_PROTOCOL_ERROR).
 */
function getBuildTimeDefault() {
  let base = import.meta.env.VITE_API_BASE_URL;
  if (base !== undefined && base !== "") {
    if (typeof window !== "undefined" && window.location?.protocol === "https:" && base.startsWith("http://")) {
      if (base.startsWith("http://150.241.244.130")) return ""; // raw IP over HTTPS causes ERR_SSL_PROTOCOL_ERROR
      base = "https://" + base.slice(7);
    }
    return base;
  }
  // When running on localhost (dev), use relative paths (goes through Vite proxy to localhost:3001) unless VITE_API_BASE_URL is set
  // If you want to use cloud server directly, set VITE_API_BASE_URL=http://150.241.244.130:10000
  // If you want to use local server directly (bypass proxy), set VITE_API_BASE_URL=http://localhost:3001
  if (import.meta.env.MODE !== "production") {
    // Return empty string so api() returns relative paths, which Vite will proxy to localhost:3001
    return "";
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    const o = window.location.origin;
    if (o.startsWith("http://150.241.244.130") || o.startsWith("http://localhost") || o.startsWith("https://localhost")) return "";
  }
  // Production on HTTPS (e.g. GitHub Pages): no raw IP; use API_BASE_URL secret or api-config.json
  if (typeof window !== "undefined" && window.location?.protocol === "https:") return "";
  return CLOUD_API;
}

function getApiBaseUrl() {
  if (runtimeApiBaseUrl) return runtimeApiBaseUrl;
  return getBuildTimeDefault();
}

/** Load API URL from api-config.json (used on GitHub Pages so data works after cloud restart). */
function loadRuntimeApiConfig() {
  if (typeof window === "undefined") return Promise.resolve();
  const base = (typeof import.meta !== "undefined" && import.meta.env?.BASE_URL) || "/";
  const basePath = base === "./" || base === "." ? "" : (base.replace(/\/$/, "") || "");
  const path = (basePath ? basePath + "/" : "") + "api-config.json";
  const url = new URL(path, window.location.origin).href;
  const fetchUrl = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
  if (window.location?.hostname?.includes("github.io") && !fetchLoggedOnce) {
    fetchLoggedOnce = true;
    console.log("[LAB] Fetching api-config.json:", url);
  }
  return fetch(fetchUrl)
    .then((res) => {
      if (window.location?.hostname?.includes("github.io") && !res.ok) {
        console.log("[LAB] api-config.json not found (", res.status, "). Set API_BASE_URL secret and run Deploy frontend to GitHub Pages.");
      }
      return res.ok ? res.json() : null;
    })
    .then((j) => {
      if (!j) return;
      // Support both apiBaseUrl and tunnelUrl (e.g. from /api/tunnel-url)
      const raw = typeof j.apiBaseUrl === "string" ? j.apiBaseUrl : (typeof j.tunnelUrl === "string" ? j.tunnelUrl : "");
      const url = raw.replace(/\/$/, "").trim();
      if (url) {
        const changed = runtimeApiBaseUrl !== url;
        runtimeApiBaseUrl = url;
        if (window.location?.hostname?.includes("github.io")) console.log("[LAB] api-config.json loaded, API base:", url);
        if (changed) window.dispatchEvent(new CustomEvent("api-config-loaded"));
      } else if (window.location?.hostname?.includes("github.io") && !loggedEmptyOnce) {
        loggedEmptyOnce = true;
        console.log("[LAB] api-config.json has empty apiBaseUrl/tunnelUrl. Set API_BASE_URL secret: https://github.com/Loveleet/lab_live/settings/secrets/actions then run Actions → Update API config (or Deploy frontend to GitHub Pages).");
      }
    })
    .catch(() => {
      if (window.location?.hostname?.includes("github.io")) console.log("[LAB] api-config.json fetch failed. Set API_BASE_URL secret and run Deploy workflow.");
    });
}

if (typeof window !== "undefined") {
  loadRuntimeApiConfig();
  // Re-fetch api-config.json every 2 min so open page picks up new tunnel URL after cloud restart (no refresh needed)
  if (window.location?.hostname?.includes("github.io")) {
    setInterval(loadRuntimeApiConfig, 2 * 60 * 1000);
  }
}

/** Initial value; use getApiBaseUrl() for current value (updates after api-config.json loads). */
export const API_BASE_URL = typeof window !== "undefined" ? getApiBaseUrl() : "";

// Log URLs in console (so user can verify page URL and API base in DevTools)
if (typeof window !== "undefined" && window.location?.hostname?.includes("github.io")) {
  console.log("[LAB] Page URL:", window.location.href);
  if (API_BASE_URL) {
    console.log("[LAB] API base URL (build-time):", API_BASE_URL);
  } else {
    console.log("[LAB] API not set. Add tunnel URL: https://github.com/Loveleet/lab_live/settings/secrets/actions → API_BASE_URL (or wait for api-config.json)");
  }
}

export { getApiBaseUrl, loadRuntimeApiConfig };

let _apiDebugLogged = false;
export function api(path) {
  const base = getApiBaseUrl();
  const fullUrl = base ? `${base.replace(/\/$/, "")}${path.startsWith("/") ? path : `/${path}`}` : path;
  if (typeof window !== "undefined") {
    if (!_apiDebugLogged) {
      _apiDebugLogged = true;
      console.log("[API DEBUG] API base URL:", base || "(empty - requests will use Vite proxy to localhost:3001)");
      if (window.location?.hostname === "localhost") {
        if (!base) {
          console.log("[API DEBUG] Using Vite proxy (localhost:3001). To use cloud API directly, set VITE_API_BASE_URL=http://150.241.244.130:10000");
        } else if (base.includes("localhost:3001")) {
          console.log("[API DEBUG] Using local server directly (bypassing proxy)");
        } else if (base.includes("150.241.244.130")) {
          console.log("[API DEBUG] Using cloud API directly");
        }
      }
    }
    console.log("[API DEBUG] api(\"" + path + "\") ->", fullUrl);
  }
  return fullUrl;
}

/** Base URL for the signals API (api_signals.py). On localhost we call local Python (5001); otherwise same as main API. */
function getSignalsApiBaseUrl() {
  if (typeof window !== "undefined" && (window.location?.hostname === "localhost" || window.location?.hostname === "127.0.0.1")) {
    const env = import.meta.env.VITE_SIGNALS_API_BASE_URL;
    if (env !== undefined && env !== "") return env.replace(/\/$/, "");
    return "http://localhost:5001";
  }
  return getApiBaseUrl();
}

export function apiSignals(path) {
  const base = getSignalsApiBaseUrl();
  return base ? `${base.replace(/\/$/, "")}${path.startsWith("/") ? path : `/${path}`}` : path;
}
