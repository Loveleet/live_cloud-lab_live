/**
 * Auth: cookie-based login via POST /auth/login, GET /auth/me, POST /auth/logout.
 * All API calls use credentials: "include" so the session cookie is sent.
 */

import React from "react";
import { api, getApiBaseUrl } from "./config";

export const AuthContext = React.createContext(null);

/** Use anywhere inside AuthContext.Provider to show a logout button. Uses triggerLogout when provided (shows 15 min countdown if enabled). */
export function LogoutButton({ className = "", ...rest }) {
  const auth = React.useContext(AuthContext);
  if (!auth) return null;
  const handleLogout = auth.triggerLogout || auth.logout;
  return (
    <button
      type="button"
      onClick={handleLogout}
      title="Log out"
      className={
        className ||
        "px-2 py-1 rounded bg-red-600 hover:bg-red-700 text-white text-sm font-semibold transition-colors"
      }
      {...rest}
    >
      Logout
    </button>
  );
}

/** Display logged-in user email (top right, near Logout) */
export function UserEmailDisplay({ className = "" }) {
  const auth = React.useContext(AuthContext);
  const email = auth?.user?.email;
  if (!email) return null;
  return (
    <span
      className={`text-white/90 text-sm truncate max-w-[180px] ${className}`}
      title={email}
    >
      {email}
    </span>
  );
}

/** Login with email + password. Returns { ok, user } on success, throws on failure. */
export async function loginWithCredentials(email, password) {
  const em = (email || "").trim();
  const pw = (password || "").trim();
  if (!em || !pw) throw new Error("email and password required");
  const base = getApiBaseUrl();
  const url = base ? `${base.replace(/\/$/, "")}/auth/login` : "/auth/login";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email: em, password: pw }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.error || "Invalid credentials");
  if (!data?.ok || !data?.user) throw new Error("Login failed");
  return { ok: true, user: data.user };
}

/** Logout: clear server session and cookie. */
export async function logoutApi() {
  const base = getApiBaseUrl();
  const url = base ? `${base.replace(/\/$/, "")}/auth/logout` : "/auth/logout";
  await fetch(url, { method: "POST", credentials: "include" }).catch(() => {});
}

/** Check current session. Returns { ok, user } or null if not logged in. */
export async function checkSession() {
  const url = api("/auth/me");
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) return null;
  const data = await res.json().catch(() => ({}));
  return data?.ok && data?.user ? data : null;
}

/** Extend session (call when user clicks "Stay logged in" after 1 hour). */
export async function extendSession() {
  const url = api("/auth/extend-session");
  const res = await fetch(url, { method: "POST", credentials: "include" });
  if (!res.ok) return false;
  const data = await res.json().catch(() => ({}));
  return !!data?.ok;
}

// Legacy exports for compatibility
export const AUTH_STORAGE_KEY = "lab_trading_auth";
export const SESSION_DURATION_MS = 7 * 24 * 60 * 60 * 1000;
export const SESSION_WARNING_BEFORE_MS = 60 * 60 * 1000;
export function getSession() { return null; }
export function setSession() {}
export function clearSession() {}
export function isSessionExpired() { return false; }
export function isSessionWarningTime() { return false; }
export function isAuthenticated() { return false; }
export function setAuthenticated() {}
