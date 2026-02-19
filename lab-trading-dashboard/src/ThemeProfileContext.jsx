/**
 * Theme profile (Anish, Loveleet, or custom): list and active profile stored in localStorage only. No server.
 */

import React, { useState, useEffect, useCallback, useImperativeHandle, useRef } from "react";
import { AuthContext } from "./auth";

/** Theme names that cannot be deleted (Loveleet, Anish) */
export const PROTECTED_THEME_NAMES = ["loveleet", "anish"];

const BUILTIN_PROFILES = [
  { id: 1, name: "Anish" },
  { id: 2, name: "Loveleet" },
];
const STORAGE_ACTIVE_ID = "active_theme_profile_id";
const STORAGE_CUSTOM_PROFILES = "theme_profiles_custom";

export const ThemeProfileContext = React.createContext(null);

function loadCustomProfiles() {
  try {
    const raw = localStorage.getItem(STORAGE_CUSTOM_PROFILES);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter((p) => p && p.id != null && p.name) : [];
  } catch (_) {
    return [];
  }
}

function saveCustomProfiles(list) {
  try {
    localStorage.setItem(STORAGE_CUSTOM_PROFILES, JSON.stringify(list));
  } catch (_) {}
}

export function ThemeProfileProvider({ children, isLoggedIn, onSettingsLoaded, themeProfileRef }) {
  const [customProfiles, setCustomProfiles] = useState([]);
  const [activeId, setActiveIdState] = useState(null);
  const profiles = [...BUILTIN_PROFILES, ...customProfiles];
  const activeProfile = activeId != null ? profiles.find((p) => p.id === activeId) || { id: activeId, name: "?" } : null;

  useEffect(() => {
    if (!isLoggedIn) {
      setCustomProfiles([]);
      setActiveIdState(null);
      return;
    }
    setCustomProfiles(loadCustomProfiles());
    try {
      const v = localStorage.getItem(STORAGE_ACTIVE_ID);
      if (v != null && v !== "") {
        const n = parseInt(v, 10);
        if (!Number.isNaN(n)) setActiveIdState(n);
        else setActiveIdState(BUILTIN_PROFILES[0]?.id ?? null);
      } else {
        setActiveIdState(BUILTIN_PROFILES[0]?.id ?? null);
      }
    } catch (_) {
      setActiveIdState(BUILTIN_PROFILES[0]?.id ?? null);
    }
  }, [isLoggedIn]);

  const setActiveProfileId = useCallback((themeProfileId) => {
    setActiveIdState(themeProfileId);
    try {
      if (themeProfileId != null) localStorage.setItem(STORAGE_ACTIVE_ID, String(themeProfileId));
      else localStorage.removeItem(STORAGE_ACTIVE_ID);
    } catch (_) {}
    return true;
  }, []);

  const refetchSettings = useCallback(async () => ({ settings: [] }), []);

  const saveSetting = useCallback((key, value) => {
    try {
      const str = typeof value === "string" ? value : JSON.stringify(value);
      if (key === "theme") localStorage.setItem("theme", value);
      else localStorage.setItem(key, str);
    } catch (_) {}
    return true;
  }, []);

  const createProfile = useCallback((name) => {
    const trimmed = (name || "").trim();
    if (!trimmed) return { ok: false, error: "Name required" };
    const existing = [...BUILTIN_PROFILES, ...customProfiles];
    const maxId = existing.length ? Math.max(...existing.map((p) => Number(p.id) || 0)) : 2;
    const newProfile = { id: maxId + 1, name: trimmed };
    const next = [...customProfiles, newProfile];
    setCustomProfiles(next);
    saveCustomProfiles(next);
    return { ok: true, profile: newProfile };
  }, [customProfiles]);

  const deleteProfile = useCallback((themeProfileId) => {
    const remaining = customProfiles.filter((p) => p.id !== themeProfileId);
    setCustomProfiles(remaining);
    saveCustomProfiles(remaining);
    if (activeId === themeProfileId) {
      const nextId = BUILTIN_PROFILES[0]?.id ?? remaining[0]?.id ?? null;
      setActiveProfileId(nextId);
    }
    return { ok: true };
  }, [customProfiles, activeId, setActiveProfileId]);

  const value = {
    profiles,
    activeProfile,
    activeThemeProfileId: activeProfile?.id ?? null,
    loading: false,
    setActiveProfileId,
    refetchSettings,
    saveSetting,
    createProfile,
    deleteProfile,
  };

  useImperativeHandle(themeProfileRef, () => ({
    saveSetting,
    activeProfile,
    activeThemeProfileId: activeProfile?.id ?? null,
    refetchSettings,
  }), [saveSetting, activeProfile]);

  return (
    <ThemeProfileContext.Provider value={value}>
      {children}
    </ThemeProfileContext.Provider>
  );
}

/** Dropdown to select theme profile (Anish, Loveleet, or custom). Show only when logged in. */
export function ThemeProfileSelector({ className = "" }) {
  const ctx = React.useContext(ThemeProfileContext);
  const [newName, setNewName] = React.useState("");

  if (!ctx) return null;
  const { profiles, activeProfile, setActiveProfileId, createProfile } = ctx;

  const handleCreate = () => {
    const name = newName.trim();
    if (!name) return;
    const result = createProfile(name);
    setNewName("");
    if (result?.ok && result?.profile) setActiveProfileId(result.profile.id);
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
          disabled={!newName.trim()}
          className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-sm"
        >
          + New
        </button>
      </div>
    </div>
  );
}

/** Profile button that opens a dropdown: user email, select theme, create/delete themes (Loveleet & Anish cannot be deleted), logout. */
export function ProfilePanel({ buttonClassName = "" }) {
  const auth = React.useContext(AuthContext);
  const ctx = React.useContext(ThemeProfileContext);
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState("");
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

  const handleCreate = () => {
    const name = newName.trim();
    if (!name) return;
    setError("");
    const result = createProfile(name);
    setNewName("");
    if (result?.ok && result?.profile) setActiveProfileId(result.profile.id);
    else if (result?.error) setError(result.error);
  };

  const handleDelete = (id, name) => {
    if (isProtected(name)) return;
    if (!window.confirm(`Delete theme "${name}"?`)) return;
    setError("");
    setDeletingId(id);
    const result = deleteProfile(id);
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
        {activeProfile?.name ?? "Profile"}
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
                disabled={!newName.trim()}
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
