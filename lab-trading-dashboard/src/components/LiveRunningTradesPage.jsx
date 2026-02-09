import React, { useState, useEffect, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { formatTradeData } from "./TableView";
import { LogoutButton } from "../auth";
import { API_BASE_URL } from "../config";

const DEMO_PASSWORD = "demo123";

function stripHtml(str) {
  if (str == null) return "";
  const s = String(str);
  if (typeof document === "undefined") return s.replace(/<[^>]+>/g, "").trim();
  const div = document.createElement("div");
  div.innerHTML = s;
  return (div.textContent || "").trim();
}

export default function LiveRunningTradesPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [rawTrades, setRawTrades] = useState(() => location.state?.trades ?? []);
  const [formattedRows, setFormattedRows] = useState(() => {
    const state = location.state;
    if (state?.formattedRows?.length) return state.formattedRows;
    if (state?.trades?.length) return state.trades.map((t, i) => formatTradeData(t, i));
    return [];
  });
  const [loading, setLoading] = useState(!location.state?.trades?.length);
  const [selected, setSelected] = useState(new Set());
  const [rowAmounts, setRowAmounts] = useState({});
  const [masterExecAmount, setMasterExecAmount] = useState("");
  const [masterInvAmount, setMasterInvAmount] = useState("");
  const [masterStopPrice, setMasterStopPrice] = useState("");
  const [passwordModal, setPasswordModal] = useState({ open: false, action: null });
  const [password, setPassword] = useState("");
  const [confirmModal, setConfirmModal] = useState({ open: false, action: null, rows: [] });
  const [successMessage, setSuccessMessage] = useState("");

  const list = rawTrades;
  const rows = formattedRows;
  const dataCols = rows.length ? Object.keys(rows[0]).filter((k) => k !== "📋") : [];

  useEffect(() => {
    if (location.state?.trades?.length) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/trades`);
        if (cancelled || !res.ok) return;
        const data = await res.json();
        if (cancelled || !Array.isArray(data)) return;
        const running = data.filter((t) => t.type === "running" || t.type === "hedge_hold");
        setRawTrades(running);
        setFormattedRows(running.map((t, i) => formatTradeData(t, i)));
      } catch (_) {}
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [location.state?.trades?.length]);

  const toggleSelect = useCallback((index) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    if (selected.size >= rows.length) setSelected(new Set());
    else setSelected(new Set(rows.map((_, i) => i)));
  }, [rows.length, selected.size]);

  const getRowAmount = (index, key) => rowAmounts[`${index}_${key}`] ?? "";
  const setRowAmount = (index, key, value) => {
    setRowAmounts((prev) => ({ ...prev, [`${index}_${key}`]: value }));
  };

  const openPasswordForAction = (action) => {
    const indices = [...selected];
    if (indices.length === 0) {
      setSuccessMessage("Select at least one trade.");
      return;
    }
    setPasswordModal({ open: true, action });
    setPassword("");
  };

  const handlePasswordConfirm = () => {
    const p = (password || "").trim();
    if (!p) return;
    if (DEMO_PASSWORD && p !== DEMO_PASSWORD) return;
    setPasswordModal((m) => ({ ...m, open: false }));
    const indices = [...selected];
    const confirmRows = indices.map((idx) => ({
      index: idx,
      raw: rawTrades[idx],
      formatted: rows[idx],
      execAmount: getRowAmount(idx, "exec") || masterExecAmount,
      invAmount: getRowAmount(idx, "inv") || masterInvAmount,
      stopPrice: getRowAmount(idx, "stop") || masterStopPrice,
    }));
    setConfirmModal({ open: true, action: passwordModal.action, rows: confirmRows });
  };

  const executeBatch = useCallback(async () => {
    setConfirmModal((m) => ({ ...m, open: false }));
    await new Promise((r) => setTimeout(r, 400));
    setSuccessMessage("Success!");
    setTimeout(() => setSuccessMessage(""), 2000);
  }, []);

  const openLive = (formattedRow, rawTrade) => {
    const stateKey = `liveTradeViewState_${Date.now()}`;
    try {
      localStorage.setItem(stateKey, JSON.stringify({ formattedRow, rawTrade }));
    } catch (_) {}
    const url = `${window.location.origin}${(window.location.pathname || "/").replace(/\/?$/, "")}/live-trade-view?stateKey=${encodeURIComponent(stateKey)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  if (loading && rows.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0f0f0f] text-white">
        <p>Loading running trades…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f5f6fa] dark:bg-[#0f0f0f] text-[#222] dark:text-gray-200 p-4">
      <div className="flex items-center justify-between gap-4 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white font-medium"
          >
            ← Back
          </button>
          <LogoutButton className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white font-medium" />
        </div>
        <h1 className="text-xl font-semibold">Live — All running trades</h1>
      </div>

      {successMessage && (
        <div className="mb-4 p-3 rounded-lg bg-green-600 text-white text-center font-medium">
          {successMessage}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#181a20] text-sm">
          <thead>
            <tr className="bg-teal-800 text-white">
              <th className="border p-1 w-10">Select</th>
              <th className="border p-1">Execute</th>
              <th className="border p-1">End Trade</th>
              <th className="border p-1">Hedge</th>
              <th className="border p-1">Add Inv</th>
              <th className="border p-1 min-w-[80px]">Inv amt</th>
              <th className="border p-1 min-w-[80px]">Exec amt</th>
              <th className="border p-1 min-w-[90px]">Stop price</th>
              <th className="border p-1">Set stop</th>
              <th className="border p-1">Live</th>
              {dataCols.map((col) => (
                <th key={col} className="border p-1 whitespace-nowrap">{col.replace(/_/g, " ")}</th>
              ))}
            </tr>
            <tr className="bg-teal-700/80 text-white">
              <td className="border p-1 text-center">
                <input
                  type="checkbox"
                  checked={rows.length > 0 && selected.size === rows.length}
                  onChange={toggleSelectAll}
                  title="Select all"
                />
              </td>
              <td className="border p-1">
                <button
                  type="button"
                  onClick={() => openPasswordForAction("execute")}
                  className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold"
                >
                  Execute
                </button>
              </td>
              <td className="border p-1">
                <button
                  type="button"
                  onClick={() => openPasswordForAction("endTrade")}
                  className="px-2 py-1 rounded bg-red-600 hover:bg-red-700 text-white text-xs font-semibold"
                >
                  End Trade
                </button>
              </td>
              <td className="border p-1">
                <button
                  type="button"
                  onClick={() => openPasswordForAction("hedge")}
                  className="px-2 py-1 rounded bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold"
                >
                  Hedge
                </button>
              </td>
              <td className="border p-1">
                <button
                  type="button"
                  onClick={() => openPasswordForAction("addInvestment")}
                  className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold"
                >
                  Add Inv
                </button>
              </td>
              <td className="border p-1">
                <input
                  type="text"
                  placeholder="Inv"
                  value={masterInvAmount}
                  onChange={(e) => setMasterInvAmount(e.target.value)}
                  className="w-full border rounded px-1 py-0.5 bg-white dark:bg-[#222] text-[#222] dark:text-gray-200 text-xs"
                />
              </td>
              <td className="border p-1">
                <input
                  type="text"
                  placeholder="Exec"
                  value={masterExecAmount}
                  onChange={(e) => setMasterExecAmount(e.target.value)}
                  className="w-full border rounded px-1 py-0.5 bg-white dark:bg-[#222] text-[#222] dark:text-gray-200 text-xs"
                />
              </td>
              <td className="border p-1">
                <input
                  type="text"
                  placeholder="Stop"
                  value={masterStopPrice}
                  onChange={(e) => setMasterStopPrice(e.target.value)}
                  className="w-full border rounded px-1 py-0.5 bg-white dark:bg-[#222] text-[#222] dark:text-gray-200 text-xs"
                />
              </td>
              <td className="border p-1">
                <button
                  type="button"
                  onClick={() => openPasswordForAction("setStopPrice")}
                  className="px-2 py-1 rounded bg-gray-600 hover:bg-gray-700 text-white text-xs font-semibold"
                >
                  Set stop
                </button>
              </td>
              <td className="border p-1" />
              <td className="border p-1" />
              {dataCols.map((col) => (
                <td key={col} className="border p-1 opacity-70 text-xs">—</td>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className={selected.has(rowIndex) ? "bg-teal-100 dark:bg-teal-900/30" : ""}>
                <td className="border p-1 text-center">
                  <input
                    type="checkbox"
                    checked={selected.has(rowIndex)}
                    onChange={() => toggleSelect(rowIndex)}
                  />
                </td>
                <td className="border p-1">
                  <button
                    type="button"
                    onClick={() => { setSelected(new Set([rowIndex])); openPasswordForAction("execute"); }}
                    className="px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs"
                  >
                    Execute
                  </button>
                </td>
                <td className="border p-1">
                  <button
                    type="button"
                    onClick={() => { setSelected(new Set([rowIndex])); openPasswordForAction("endTrade"); }}
                    className="px-2 py-0.5 rounded bg-red-600 hover:bg-red-700 text-white text-xs"
                  >
                    End
                  </button>
                </td>
                <td className="border p-1">
                  <button
                    type="button"
                    onClick={() => { setSelected(new Set([rowIndex])); openPasswordForAction("hedge"); }}
                    className="px-2 py-0.5 rounded bg-amber-600 hover:bg-amber-700 text-white text-xs"
                  >
                    Hedge
                  </button>
                </td>
                <td className="border p-1">
                  <button
                    type="button"
                    onClick={() => { setSelected(new Set([rowIndex])); openPasswordForAction("addInvestment"); }}
                    className="px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs"
                  >
                    Add Inv
                  </button>
                </td>
                <td className="border p-1">
                  <input
                    type="text"
                    placeholder="0"
                    value={getRowAmount(rowIndex, "inv")}
                    onChange={(e) => setRowAmount(rowIndex, "inv", e.target.value)}
                    className="w-full border rounded px-1 py-0.5 bg-white dark:bg-[#222] text-[#222] dark:text-gray-200 text-xs max-w-[70px]"
                  />
                </td>
                <td className="border p-1">
                  <input
                    type="text"
                    placeholder="0"
                    value={getRowAmount(rowIndex, "exec")}
                    onChange={(e) => setRowAmount(rowIndex, "exec", e.target.value)}
                    className="w-full border rounded px-1 py-0.5 bg-white dark:bg-[#222] text-[#222] dark:text-gray-200 text-xs max-w-[70px]"
                  />
                </td>
                <td className="border p-1">
                  <input
                    type="text"
                    placeholder="—"
                    value={getRowAmount(rowIndex, "stop")}
                    onChange={(e) => setRowAmount(rowIndex, "stop", e.target.value)}
                    className="w-full border rounded px-1 py-0.5 bg-white dark:bg-[#222] text-[#222] dark:text-gray-200 text-xs max-w-[80px]"
                  />
                </td>
                <td className="border p-1">
                  <button
                    type="button"
                    onClick={() => { setSelected(new Set([rowIndex])); openPasswordForAction("setStopPrice"); }}
                    className="px-2 py-0.5 rounded bg-gray-600 hover:bg-gray-700 text-white text-xs"
                  >
                    Set
                  </button>
                </td>
                <td className="border p-1">
                  <button
                    type="button"
                    onClick={() => openLive(row, rawTrades[rowIndex])}
                    className="px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold"
                  >
                    Live
                  </button>
                </td>
                {dataCols.map((col) => (
                  <td key={col} className="border p-1 align-top">
                    {col === "Pair" ? (
                      <span dangerouslySetInnerHTML={{ __html: row[col] ?? "" }} />
                    ) : (
                      stripHtml(String(row[col] ?? ""))
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {passwordModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setPasswordModal((m) => ({ ...m, open: false }))}>
          <div className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-sm w-full shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-semibold text-lg mb-2">Password</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">Enter password to confirm.</p>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handlePasswordConfirm();
                }
              }}
              placeholder="Password"
              className="w-full border-2 rounded-lg px-3 py-2 mb-4 bg-white dark:bg-[#333] text-[#222] dark:text-gray-200"
            />
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setPasswordModal((m) => ({ ...m, open: false }))} className="px-3 py-1.5 rounded-lg bg-gray-200 dark:bg-gray-700">Cancel</button>
              <button type="button" onClick={handlePasswordConfirm} className="px-4 py-1.5 rounded-lg bg-teal-600 text-white">Confirm</button>
            </div>
          </div>
        </div>
      )}

      {confirmModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setConfirmModal((m) => ({ ...m, open: false }))}>
          <div className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-2xl w-full max-h-[80vh] overflow-auto shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-semibold text-lg mb-2">Confirm — {confirmModal.action}</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Review and edit amounts if needed, then confirm.</p>
            <ul className="space-y-2 mb-4">
              {confirmModal.rows.map((r, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2 p-2 rounded border border-gray-200 dark:border-gray-700">
                  <span className="font-medium">{stripHtml(r.formatted.Pair) || r.raw?.pair || "—"}</span>
                  {(confirmModal.action === "execute" || confirmModal.action === "addInvestment") && (
                    <input
                      type="text"
                      placeholder="Amount"
                      defaultValue={r.execAmount || r.invAmount}
                      className="border rounded px-2 py-1 w-24 text-sm bg-white dark:bg-[#333]"
                    />
                  )}
                  {confirmModal.action === "setStopPrice" && (
                    <input
                      type="text"
                      placeholder="Stop price"
                      defaultValue={r.stopPrice}
                      className="border rounded px-2 py-1 w-24 text-sm bg-white dark:bg-[#333]"
                    />
                  )}
                </li>
              ))}
            </ul>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setConfirmModal((m) => ({ ...m, open: false }))} className="px-3 py-1.5 rounded-lg bg-gray-200 dark:bg-gray-700">Cancel</button>
              <button type="button" onClick={executeBatch} className="px-4 py-1.5 rounded-lg bg-teal-600 text-white">Execute</button>
            </div>
          </div>
        </div>
      )}

      {rows.length === 0 && !loading && (
        <p className="text-center text-gray-500 py-8">No running trades.</p>
      )}
    </div>
  );
}
