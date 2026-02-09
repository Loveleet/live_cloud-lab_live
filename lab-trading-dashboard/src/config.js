/** Cloud API (direct IP). Used when not on localhost and not GitHub Pages. */
const CLOUD_API = "http://150.241.244.130:10000";

/** Local API (Node server). Vite dev server proxies /api to this. */
const LOCAL_API_PORT = 10000;
const LOCAL_API = `http://localhost:${LOCAL_API_PORT}`;

/** Set by runtime config (api-config.json) when loaded — so GitHub Pages keeps working after cloud reboot */
let runtimeApiBaseUrl = null;
let loggedEmptyOnce = false;
let fetchLoggedOnce = false;

/** True when app is running in browser on localhost (dev). */
function isLocalhostOrigin() {
  if (typeof window === "undefined") return false;
  const h = window.location?.hostname || "";
  return h === "localhost" || h === "127.0.0.1";
}

/**
 * Build-time default (env or cloud IP). On HTTPS we never use raw IP (no valid cert → ERR_SSL_PROTOCOL_ERROR).
 * Localhost: use relative URLs so Vite proxy forwards /api to localhost:10000 (or use env override).
 * GitHub Pages: no default here; runtime api-config.json or build secret.
 * Other: cloud API.
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
  // LOCALHOST: use empty base so fetch("/api/...") goes to same origin → Vite proxy → localhost:10000
  // Unless user chose "Use cloud data" after local server was down
  if (typeof window !== "undefined" && isLocalhostOrigin()) {
    if (localhostUseCloudFallback) return CLOUD_API;
    return ""; // Relative URLs; Vite proxy in vite.config.js forwards /api to http://localhost:10000
  }
  // Cloud server (150.241.244.130): same-origin
  if (typeof window !== "undefined" && window.location?.origin) {
    const o = window.location.origin;
    if (o.startsWith("http://150.241.244.130") || o.startsWith("https://localhost")) return "";
  }
  // Production on HTTPS (e.g. GitHub Pages): no raw IP; use API_BASE_URL secret or api-config.json
  if (typeof window !== "undefined" && window.location?.protocol === "https:") return "";
  // Dev build but not in browser on localhost, or production on HTTP: use cloud
  return CLOUD_API;
}

/** When true, we are on the cloud server — always use same-origin API, ignore api-config.json */
function isCloudServerOrigin() {
  if (typeof window === "undefined") return false;
  const h = window.location?.hostname || "";
  return h === "150.241.244.130";
}

function getApiBaseUrl() {
  // When served from cloud server, always use same origin so /api/* hits this server (real olab data)
  if (isCloudServerOrigin()) return "";
  
  // On GitHub Pages, ALWAYS prefer runtime api-config.json over build-time URL (tunnel URL changes)
  const isGitHubPages = typeof window !== "undefined" && window.location?.hostname?.includes("github.io");
  if (isGitHubPages && runtimeApiBaseUrl) {
    return runtimeApiBaseUrl; // Runtime config always wins on GitHub Pages
  }
  
  if (runtimeApiBaseUrl) return runtimeApiBaseUrl;
  return getBuildTimeDefault();
}

/** Load API URL from api-config.json (used on GitHub Pages so data works after cloud restart). */
function loadRuntimeApiConfig() {
  if (typeof window === "undefined") return Promise.resolve();
  // When on cloud server, don't load api-config — we use same-origin API only
  if (isCloudServerOrigin()) return Promise.resolve();
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
      if (window.location?.hostname?.includes("github.io")) {
        if (!res.ok) {
          console.error(`[LAB] api-config.json not found (${res.status}). URL tried: ${url}`);
          console.error("[LAB] Set API_BASE_URL secret and run Deploy frontend to GitHub Pages.");
          // Try fallback: check if file exists at root (old deploy structure)
          if (res.status === 404 && basePath) {
            const rootUrl = new URL("api-config.json", window.location.origin).href;
            console.log("[LAB] Trying fallback location:", rootUrl);
            return fetch(rootUrl + "?t=" + Date.now()).catch(() => res);
          }
        } else {
          console.log("[LAB] api-config.json found, parsing...");
        }
      }
      return res.ok ? res.json() : null;
    })
    .then((j) => {
      if (!j) {
        if (window.location?.hostname?.includes("github.io")) {
          console.warn("[LAB] api-config.json is empty or invalid. Using build-time default if available.");
        }
        return;
      }
      // Support both apiBaseUrl and tunnelUrl (e.g. from /api/tunnel-url)
      const raw = typeof j.apiBaseUrl === "string" ? j.apiBaseUrl : (typeof j.tunnelUrl === "string" ? j.tunnelUrl : "");
      const url = raw.replace(/\/$/, "").trim();
      if (url) {
        const oldUrl = runtimeApiBaseUrl;
        const changed = oldUrl !== url;
        runtimeApiBaseUrl = url;
        if (window.location?.hostname?.includes("github.io")) {
          console.log("[LAB] ✅ api-config.json loaded, API base:", url);
          if (oldUrl) {
            console.log("[LAB] ⚠️ API base changed from", oldUrl, "to", url);
          }
        }
        if (changed) {
          console.log("[LAB] API base changed, triggering refresh");
          window.dispatchEvent(new CustomEvent("api-config-loaded"));
        } else if (!oldUrl && window.location?.hostname?.includes("github.io")) {
          // First time loading - still trigger refresh to use the new URL
          console.log("[LAB] First time api-config loaded, triggering refresh");
          window.dispatchEvent(new CustomEvent("api-config-loaded"));
        }
      } else if (window.location?.hostname?.includes("github.io") && !loggedEmptyOnce) {
        loggedEmptyOnce = true;
        console.warn("[LAB] api-config.json has empty apiBaseUrl/tunnelUrl. Set API_BASE_URL secret: https://github.com/Loveleet/lab_live/settings/secrets/actions then run Actions → Update API config (or Deploy frontend to GitHub Pages).");
      }
    })
    .catch((err) => {
      if (window.location?.hostname?.includes("github.io")) {
        console.error("[LAB] api-config.json fetch failed:", err.message);
        console.error("[LAB] Set API_BASE_URL secret and run Deploy workflow.");
      }
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
  const buildTimeUrl = import.meta.env.VITE_API_BASE_URL;
  if (buildTimeUrl) {
    console.log("[LAB] ⚠️ Build-time API URL:", buildTimeUrl, "(may be stale - api-config.json will override)");
  }
  if (API_BASE_URL && !runtimeApiBaseUrl) {
    console.log("[LAB] Using build-time API URL:", API_BASE_URL, "- waiting for api-config.json to load...");
  } else if (!API_BASE_URL) {
    console.log("[LAB] API not set. Add tunnel URL: https://github.com/Loveleet/lab_live/settings/secrets/actions → API_BASE_URL (or wait for api-config.json)");
  }
}

/** When true, localhost uses cloud API instead of local (used after "Use cloud data" when local server is down). */
let localhostUseCloudFallback = false;
export function setLocalhostUseCloudFallback(value) {
  localhostUseCloudFallback = !!value;
}
export function getLocalhostUseCloudFallback() {
  return localhostUseCloudFallback;
}

export { getApiBaseUrl, loadRuntimeApiConfig, isLocalhostOrigin };

/** Check if runtime api-config.json has loaded (for debugging) */
export function hasRuntimeApiConfig() {
  return !!runtimeApiBaseUrl;
}

export function api(path) {
  const base = getApiBaseUrl();
  const isGitHubPages = typeof window !== "undefined" && window.location?.hostname?.includes("github.io");
  if (!base) {
    if (isGitHubPages) {
      console.warn("[api()] No API base URL — api-config.json may not have loaded yet");
    }
    return path; // Relative path (same origin)
  }
  const fullUrl = `${base.replace(/\/$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
  if (isGitHubPages) {
    console.log(`[api()] Built URL: ${fullUrl} (base: ${base}, path: ${path})`);
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
