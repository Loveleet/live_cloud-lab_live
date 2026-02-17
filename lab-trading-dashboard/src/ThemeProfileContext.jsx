/**
 * Theme profile (Anish, Loveleet, or custom): list, select active, save/load UI settings per profile on server.
 * Debug: open /api/debug-theme-settings in browser or check console for [Theme] logs.
 */

import React, { useState, useEffect, useCallback, useImperativeHandle, useRef } from "react";
import { api } from "./config";
import { AuthContext } from "./auth";

/** Theme names that cannot be deleted (Loveleet, Anish) */
export const PROTECTED_THEME_NAMES = ["loveleet", "anish"];

export const ThemeProfileContext = React.createContext(null);

const DEBUG = true;
function log(...args) {
  if (DEBUG && typeof console !== "undefined") console.log("[Theme]", ...args);
}

export function ThemeProfileProvider({ children, isLoggedIn, onSettingsLoaded, themeProfileRef }) {
  const [profiles, setProfiles] = useState([]);
  const [activeProfile, setActiveProfileState] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchProfiles = useCallback(async () => {
    const url = api("/api/theme-profiles");
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) return [];
    const data = await res.json().catch(() => ({}));
    const list = data?.profiles || [];
    setProfiles(list);
    log("profiles loaded", list.length, list.map((p) => p.name));
    return list;
  }, []);

  const fetchActiveProfile = useCallback(async () => {
    const url = api("/api/active-theme-profile");
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) return null;
    const data = await res.json().catch(() => ({}));
    const active = data?.activeProfile || null;
    setActiveProfileState(active);
    log("active profile", active?.name, "id=", active?.id);
    return active;
  }, []);

  useEffect(() => {
    if (!isLoggedIn) {
      setProfiles([]);
      setActiveProfileState(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all([fetchProfiles(), fetchActiveProfile()])
      .then(([list, active]) => {
        if (cancelled) return;
        if (!active && list.length > 0) {
          log("no active profile; defaulting to first:", list[0].name);
          setActiveProfileId(list[0].id);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [isLoggedIn, fetchProfiles, fetchActiveProfile]);

  const setActiveProfileId = useCallback(
    async (themeProfileId) => {
      const url = api("/api/active-theme-profile");
      const res = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme_profile_id: themeProfileId }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        log("set active profile failed", res.status, err);
        return false;
      }
      const active = themeProfileId != null ? profiles.find((p) => p.id === themeProfileId) || { id: themeProfileId, name: "?" } : null;
      setActiveProfileState(active);
      log("set active profile", active?.name, "id=", themeProfileId);
      return true;
    },
    [profiles]
  );

  const refetchSettings = useCallback(async () => {
    const themeProfileId = activeProfile?.id;
    const q = themeProfileId != null ? `?theme_profile_id=${themeProfileId}` : "";
    const url = api("/api/ui-settings") + q;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) {
      log("refetchSettings failed", res.status);
      return { settings: [] };
    }
    const data = await res.json().catch(() => ({}));
    const settings = data?.settings || [];
    log("refetchSettings", settings.length, "keys", settings.slice(0, 10).map((s) => s.key));
    return { settings };
  }, [activeProfile?.id]);

  const saveSetting = useCallback(
    async (key, value) => {
      const themeProfileId = activeProfile?.id;
      const url = api("/api/ui-settings");
      const body = { key, value };
      if (themeProfileId != null) body.theme_profile_id = themeProfileId;
      const res = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        log("saveSetting failed", key, res.status);
        return false;
      }
      log("saveSetting", key, "profile=", activeProfile?.name);
      return true;
    },
    [activeProfile]
  );

  const createProfile = useCallback(
    async (name) => {
      const url = api("/api/theme-profiles");
      const res = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: (name || "").trim() }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        log("createProfile failed", err);
        return { ok: false, error: err?.error || "Failed" };
      }
      const data = await res.json().catch(() => ({}));
      const profile = data?.profile;
      if (profile) {
        setProfiles((prev) => [...prev, profile]);
        log("createProfile", profile.name, "id=", profile.id);
        return { ok: true, profile };
      }
      return { ok: false, error: "No profile returned" };
    },
    []
  );

  const deleteProfile = useCallback(async (themeProfileId) => {
    const url = api(`/api/theme-profiles/${themeProfileId}`);
    const res = await fetch(url, { method: "DELETE", credentials: "include" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      log("deleteProfile failed", err);
      return { ok: false, error: err?.error || "Failed" };
    }
    const remaining = profiles.filter((p) => p.id !== themeProfileId);
    setProfiles(remaining);
    if (activeProfile?.id === themeProfileId) {
      const next = remaining[0];
      await setActiveProfileId(next?.id ?? null);
    }
    log("deleteProfile", themeProfileId);
    return { ok: true };
  }, [activeProfile?.id, profiles, setActiveProfileId]);

  // When active profile is set or changes, fetch settings and notify parent so it can apply to state
  useEffect(() => {
    if (!isLoggedIn || !activeProfile?.id || typeof onSettingsLoaded !== "function") return;
    let cancelled = false;
    refetchSettings().then(({ settings }) => {
      if (!cancelled) {
        log("apply server settings to app", settings.length, "keys");
        onSettingsLoaded(settings);
      }
    });
    return () => { cancelled = true; };
  }, [isLoggedIn, activeProfile?.id, onSettingsLoaded]);

  const value = {
    profiles,
    activeProfile,
    activeThemeProfileId: activeProfile?.id ?? null,
    loading,
    setActiveProfileId,
    refetchSettings,
    saveSetting,
    createProfile,
    deleteProfile,
    fetchProfiles,
    fetchActiveProfile,
  };

  useImperativeHandle(themeProfileRef, () => ({
    saveSetting,
    activeProfile,
    activeThemeProfileId: activeProfile?.id ?? null,
    refetchSettings,
  }), [saveSetting, activeProfile, refetchSettings]);

  return (
    <ThemeProfileContext.Provider value={value}>
      {children}
    </ThemeProfileContext.Provider>
  );
}

/** Dropdown to select theme profile (Anish, Loveleet, or custom). Show only when logged in. */
export function ThemeProfileSelector({ className = "", showDebug = true }) {
  const ctx = React.useContext(ThemeProfileContext);
  const [newName, setNewName] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  if (!ctx) return null;
  const { profiles, activeProfile, setActiveProfileId, createProfile } = ctx;

  const runDebugCheck = React.useCallback(async () => {
    try {
      const url = api("/api/debug-theme-settings");
      const res = await fetch(url, { credentials: "include" });
      const data = await res.json().catch(() => ({}));
      log("debug-theme-settings", data);
      if (typeof console !== "undefined") console.log("[Theme] Debug result (see Network tab for /api/debug-theme-settings):", data);
    } catch (e) {
      console.warn("[Theme] Debug check failed", e);
    }
  }, []);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    const result = await createProfile(name);
    setCreating(false);
    setNewName("");
    if (result?.ok && result?.profile) {
      await setActiveProfileId(result.profile.id);
    }
  };

  return (
    <div className={`flex items-center gap-2 flex-wrap ${className}`}>
      <span className="text-sm font-medium text-black dark:text-gray-200">View:</span>
      <select
        value={activeProfile?.id ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          setActiveProfileId(v === "" ? null : Number(v));
        }}
        className="bg-gray-200 dark:bg-gray-700 text-black dark:text-gray-200 border border-gray-400 dark:border-gray-600 rounded px-2 py-1 text-sm"
      >
        {profiles.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <div className="flex items-center gap-1">
        <input
          type="text"
          placeholder="New profile name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          className="w-28 px-2 py-1 text-sm rounded border border-gray-400 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-gray-200"
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={creating || !newName.trim()}
          className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-sm"
        >
          + New
        </button>
      </div>
      {showDebug && (
        <button
          type="button"
          onClick={runDebugCheck}
          title="Verify theme profile and settings (opens in console)"
          className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 underline"
        >
          Check
        </button>
      )}
    </div>
  );
}

/** Profile button that opens a dropdown: user email, select theme, create/delete themes (Loveleet & Anish cannot be deleted), logout. */
export function ProfilePanel({ buttonClassName = "" }) {
  const auth = React.useContext(AuthContext);
  const ctx = React.useContext(ThemeProfileContext);
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [error, setError] = useState("");
  const panelRef = useRef(null);

  React.useEffect(() => {
    const close = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false);
    };
    if (open) {
      document.addEventListener("click", close);
      return () => document.removeEventListener("click", close);
    }
  }, [open]);

  if (!auth || !ctx) return null;
  const { user, logout } = auth;
  const { profiles, activeProfile, setActiveProfileId, createProfile, deleteProfile } = ctx;

  const isProtected = (name) => PROTECTED_THEME_NAMES.includes((name || "").trim().toLowerCase());

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    setError("");
    setCreating(true);
    const result = await createProfile(name);
    setCreating(false);
    setNewName("");
    if (result?.ok && result?.profile) await setActiveProfileId(result.profile.id);
    else if (result?.error) setError(result.error);
  };

  const handleDelete = async (id, name) => {
    if (isProtected(name)) return;
    if (!window.confirm(`Delete theme "${name}"?`)) return;
    setError("");
    setDeletingId(id);
    const result = await deleteProfile(id);
    setDeletingId(null);
    if (!result?.ok && result?.error) setError(result.error);
  };

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={buttonClassName || "absolute right-56 top-3 z-20 px-3 py-2 rounded-full bg-white/80 dark:bg-gray-800/80 shadow hover:scale-105 transition-all text-sm font-semibold text-gray-700 dark:text-gray-200"}
        title="Profile & themes"
      >
        Profile
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 z-50 w-72 rounded-xl border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-900 shadow-xl py-3 px-4">
          {/* User */}
          <div className="mb-3 pb-2 border-b border-gray-200 dark:border-gray-600">
            <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">User</p>
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate" title={user?.email}>{user?.email || "—"}</p>
          </div>
          {/* Select theme */}
          <div className="mb-3">
            <label className="block text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">View (theme)</label>
            <select
              value={activeProfile?.id ?? ""}
              onChange={(e) => setActiveProfileId(e.target.value === "" ? null : Number(e.target.value))}
              className="w-full bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm"
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          {/* Create new theme */}
          <div className="mb-3">
            <label className="block text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">New theme</label>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Theme name"
                value={newName}
                onChange={(e) => { setNewName(e.target.value); setError(""); }}
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              />
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating || !newName.trim()}
                className="px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-sm font-medium"
              >
                + Add
              </button>
            </div>
          </div>
          {/* List themes with delete (except Loveleet & Anish) */}
          <div className="mb-3">
            <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">Themes</p>
            <ul className="space-y-1 max-h-32 overflow-y-auto">
              {profiles.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2 py-1">
                  <span className="text-sm text-gray-700 dark:text-gray-300 truncate">{p.name}</span>
                  {isProtected(p.name) ? (
                    <span className="text-xs text-gray-400 dark:text-gray-500 flex-shrink-0">(fixed)</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleDelete(p.id, p.name)}
                      disabled={deletingId === p.id}
                      className="text-xs text-red-600 dark:text-red-400 hover:underline disabled:opacity-50"
                    >
                      {deletingId === p.id ? "…" : "Delete"}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
          {error && <p className="text-xs text-red-600 dark:text-red-400 mb-2">{error}</p>}
          {/* Logout */}
          <div className="pt-2 border-t border-gray-200 dark:border-gray-600">
            <button
              type="button"
              onClick={() => { setOpen(false); logout(); }}
              className="w-full px-3 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-semibold"
            >
              Logout
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
