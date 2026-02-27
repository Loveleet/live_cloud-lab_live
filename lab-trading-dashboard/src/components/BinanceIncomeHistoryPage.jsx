import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../config";

const BinanceIncomeHistoryPage = () => {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [syncInfo, setSyncInfo] = useState(null);

  const [filters, setFilters] = useState({
    symbol: "",
    incomeType: "ALL",
    minPL: "",
  });

  const loadHistory = async (options = { showSyncInfo: false }) => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch("/api/income-history");
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(data.message || "Failed to load income history");
      }
      if (!Array.isArray(data.history)) {
        throw new Error("Invalid income history response");
      }
      setHistory(data.history);
      if (options.showSyncInfo && data.sync) {
        setSyncInfo({
          inserted: data.sync.inserted ?? 0,
          skipped: data.sync.skipped ?? 0,
          total: data.sync.total_received ?? data.history.length ?? 0,
          at: new Date().toISOString(),
        });
      }
    } catch (e) {
      setError(e.message || "Failed to load income history");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory({ showSyncInfo: false });
  }, []);

  const symbols = useMemo(() => {
    const set = new Set();
    history.forEach((row) => {
      if (row.symbol) set.add(row.symbol);
    });
    return Array.from(set).sort();
  }, [history]);

  const filtered = useMemo(() => {
    const minPLNum = parseFloat(filters.minPL);
    return history.filter((row) => {
      if (!row) return false;
      const symbol = (row.symbol || "").toUpperCase();
      const incomeType = (row.income_type || "").toUpperCase();
      const incomeVal = typeof row.income === "number" ? row.income : parseFloat(row.income || "0");

      if (filters.symbol && symbol !== filters.symbol.toUpperCase()) {
        return false;
      }
      if (filters.incomeType !== "ALL" && incomeType !== filters.incomeType) {
        return false;
      }
      if (!Number.isNaN(minPLNum) && incomeVal <= minPLNum) {
        return false;
      }
      return true;
    });
  }, [history, filters]);

  const handleFilterChange = (field, value) => {
    setFilters((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  return (
    <div className="p-4 md:p-6 lg:p-8 bg-[#f5f6fa] dark:bg-black min-h-screen">
      <div className="max-w-7xl mx-auto bg-white dark:bg-[#111827] rounded-xl shadow-md border border-gray-200 dark:border-gray-800 p-4 md:p-6">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-4">
          <div>
            <h1 className="text-xl md:text-2xl font-bold text-gray-900 dark:text-white">
              Binance Trade History
            </h1>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Combined Binance income history (REALIZED_PNL + COMMISSION) with filters.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => loadHistory({ showSyncInfo: true })}
              className="px-3 py-2 rounded-lg text-sm font-medium bg-teal-600 text-white hover:bg-teal-700"
              disabled={loading}
            >
              {loading ? "Syncing..." : "Sync from Binance"}
            </button>
            <button
              type="button"
              onClick={() =>
                setFilters({
                  symbol: "",
                  incomeType: "ALL",
                  minPL: "",
                })
              }
              className="px-3 py-2 rounded-lg text-sm font-medium bg-gray-200 dark:bg-gray-800 text-gray-800 dark:text-gray-100 hover:bg-gray-300 dark:hover:bg-gray-700"
            >
              Reset filters
            </button>
          </div>
        </div>

        {syncInfo && (
          <div className="mb-4 px-3 py-2 rounded-md bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-700 text-xs text-emerald-800 dark:text-emerald-100">
            Synced from Binance at{" "}
            <span className="font-semibold">
              {new Date(syncInfo.at).toLocaleString()}
            </span>
            {": "}
            <span className="font-semibold">{syncInfo.inserted}</span> inserted,{" "}
            <span className="font-semibold">{syncInfo.skipped}</span> skipped,{" "}
            <span className="font-semibold">{syncInfo.total}</span> total rows received.
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
          <div>
            <label className="block text-xs font-semibold text-gray-600 dark:text-gray-300 mb-1">
              Pair
            </label>
            <select
              className="w-full px-2 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#111827] text-sm text-gray-900 dark:text-gray-100"
              value={filters.symbol}
              onChange={(e) => handleFilterChange("symbol", e.target.value)}
            >
              <option value="">All pairs</option>
              {symbols.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 dark:text-gray-300 mb-1">
              Income type
            </label>
            <select
              className="w-full px-2 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#111827] text-sm text-gray-900 dark:text-gray-100"
              value={filters.incomeType}
              onChange={(e) => handleFilterChange("incomeType", e.target.value)}
            >
              <option value="ALL">All</option>
              <option value="REALIZED_PNL">REALIZED_PNL</option>
              <option value="COMMISSION">COMMISSION</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 dark:text-gray-300 mb-1">
              Min P/L (USDT)
            </label>
            <input
              type="number"
              step="0.01"
              placeholder="e.g. 5"
              className="w-full px-2 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#111827] text-sm text-gray-900 dark:text-gray-100"
              value={filters.minPL}
              onChange={(e) => handleFilterChange("minPL", e.target.value)}
            />
          </div>
          <div className="flex items-end">
            <div className="text-xs text-gray-500 dark:text-gray-400">
              Rows:{" "}
              <span className="font-semibold">
                {filtered.length} / {history.length}
              </span>
            </div>
          </div>
        </div>

        {loading && (
          <div className="py-10 text-center text-gray-600 dark:text-gray-300 text-sm">
            Loading income history...
          </div>
        )}
        {error && !loading && (
          <div className="py-3 mb-4 px-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-700">
            {error}
          </div>
        )}

        {!loading && !error && (
          <div className="overflow-auto rounded-lg border border-gray-200 dark:border-gray-800">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-sm">
              <thead className="bg-gray-50 dark:bg-[#020617]">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold text-gray-700 dark:text-gray-200">
                    Time
                  </th>
                  <th className="px-3 py-2 text-left font-semibold text-gray-700 dark:text-gray-200">
                    Pair
                  </th>
                  <th className="px-3 py-2 text-left font-semibold text-gray-700 dark:text-gray-200">
                    Income Type
                  </th>
                  <th className="px-3 py-2 text-right font-semibold text-gray-700 dark:text-gray-200">
                    Income (USDT)
                  </th>
                  <th className="px-3 py-2 text-left font-semibold text-gray-700 dark:text-gray-200">
                    Asset
                  </th>
                  <th className="px-3 py-2 text-left font-semibold text-gray-700 dark:text-gray-200">
                    Info
                  </th>
                  <th className="px-3 py-2 text-left font-semibold text-gray-700 dark:text-gray-200">
                    Tran ID
                  </th>
                  <th className="px-3 py-2 text-left font-semibold text-gray-700 dark:text-gray-200">
                    Trade ID
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-[#020617]">
                {filtered.map((row, idx) => {
                  const incomeVal =
                    typeof row.income === "number"
                      ? row.income
                      : parseFloat(row.income || "0");
                  const isPositive = incomeVal > 0;
                  const incomeClass = isPositive
                    ? "text-emerald-500"
                    : incomeVal < 0
                    ? "text-red-500"
                    : "text-gray-500";
                  const timeText = row.time
                    ? new Date(row.time).toLocaleString()
                    : "";
                  return (
                    <tr key={`${row.tran_id || idx}-${row.income_type || ""}`}>
                      <td className="px-3 py-2 whitespace-nowrap text-xs text-gray-700 dark:text-gray-200">
                        {timeText}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs font-semibold text-gray-900 dark:text-gray-100">
                        {row.symbol || "-"}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs text-gray-700 dark:text-gray-200">
                        {row.income_type || "-"}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs text-right">
                        <span className={incomeClass}>
                          {incomeVal.toFixed(4)}
                        </span>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs text-gray-700 dark:text-gray-200">
                        {row.asset || "-"}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs text-gray-700 dark:text-gray-200">
                        {row.info || "-"}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs text-gray-700 dark:text-gray-200">
                        {row.tran_id || "-"}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs text-gray-700 dark:text-gray-200">
                        {row.trade_id || "-"}
                      </td>
                    </tr>
                  );
                })}
                {filtered.length === 0 && (
                  <tr>
                    <td
                      className="px-3 py-6 text-center text-sm text-gray-500 dark:text-gray-400"
                      colSpan={8}
                    >
                      No income history rows match the current filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default BinanceIncomeHistoryPage;

