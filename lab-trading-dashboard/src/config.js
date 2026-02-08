/** Cloud API (direct IP). Use tunnel URL in .env.local if this isn't reachable from your network. */
const CLOUD_API = "http://150.241.244.130:10000";

/**
 * API base URL for backend. Empty = same origin.
 * When the page is HTTPS (e.g. GitHub Pages), the API URL must be HTTPS too (mixed content is blocked).
 * Local dev (npm run dev): uses VITE_API_BASE_URL from .env.local if set, else cloud so you get real data.
 * To use the cloud API instead of local: set VITE_API_BASE_URL=http://150.241.244.130:10000 in .env.local
 */
function getApiBaseUrl() {
  let base = import.meta.env.VITE_API_BASE_URL;
  if (base !== undefined && base !== "") {
    // If page is HTTPS, force API to HTTPS to avoid mixed-content block (unless it's raw IP - no valid cert)
    if (typeof window !== "undefined" && window.location?.protocol === "https:" && base.startsWith("http://")) {
      if (base.startsWith("http://150.241.244.130")) return ""; // raw IP over HTTPS causes ERR_SSL_PROTOCOL_ERROR
      base = "https://" + base.slice(7);
    }
    return base;
  }
  // Development: default to local server (server-local.js on 3001) for localhost testing
  if (import.meta.env.MODE !== "production") {
    return "http://localhost:3001";
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    const o = window.location.origin;
    if (o.startsWith("http://150.241.244.130") || o.startsWith("http://localhost") || o.startsWith("https://localhost")) return "";
  }
  // Production on HTTPS (e.g. GitHub Pages): never use raw IP with https (no valid cert → ERR_SSL_PROTOCOL_ERROR).
  // Set API_BASE_URL secret in GitHub to your Cloudflare Tunnel URL (e.g. https://xxx.trycloudflare.com) and redeploy.
  if (typeof window !== "undefined" && window.location?.protocol === "https:") {
    return "";
  }
  return CLOUD_API;
}

/** @deprecated Use getApiBaseUrl() or api() - kept for compatibility */
export const API_BASE_URL = typeof window !== "undefined" ? getApiBaseUrl() : "";

export { getApiBaseUrl };

export function api(path) {
  const base = getApiBaseUrl();
  return base ? `${base.replace(/\/$/, "")}${path.startsWith("/") ? path : `/${path}`}` : path;
}
