import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Play, Settings, Square, Shield, Crosshair, LayoutGrid } from "lucide-react";
import { formatTradeData } from "./TableView";
import { LogoutButton, UserEmailDisplay } from "../auth";
import { API_BASE_URL, api, apiFetch } from "../config";

const REFRESH_INTERVAL_KEY = "refresh_app_main_intervalSec";

const TV_SCRIPT_ID = "tradingview-widget-script-single";
function loadTradingViewScript(onReady) {
  if (typeof window !== "undefined" && window.TradingView) {
    onReady?.();
    return;
  }
  const el = document.getElementById(TV_SCRIPT_ID);
  if (el) {
    if (window.TradingView) {
      onReady?.();
      return;
    }
    el.addEventListener("load", () => {
      const check = () => {
        if (window.TradingView) onReady?.();
        else setTimeout(check, 50);
      };
      setTimeout(check, 0);
    }, { once: true });
    return;
  }
  const script = document.createElement("script");
  script.id = TV_SCRIPT_ID;
  script.src = "https://s3.tradingview.com/tv.js";
  script.async = true;
  script.onload = () => {
    const check = () => {
      if (window.TradingView) onReady?.();
      else setTimeout(check, 50);
    };
    setTimeout(check, 0);
  };
  document.body.appendChild(script);
}

const intervalMap = {
  "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D",
};
const ALL_INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"];

const getRobustSymbol = (pair) => {
  if (!pair) return "BTCUSDT";
  let symbol = String(pair).replace(/<[^>]+>/g, "").replace(/\s+/g, "").replace(/[^A-Z0-9]/gi, "").toUpperCase();
  if (symbol.startsWith("BINANCE")) symbol = symbol.slice(7);
  symbol = symbol.replace(/PERPETUALCONTRACT|PERP|CHART/gi, "").replace(/\d{6,}$/, "");
  return symbol || "BTCUSDT";
};

/** Extract trading pair (e.g. UNIUSDT) from unique_id like "UNIUSDTBUY2026-02-21..." so signals API gets the right symbol when trade is missing from DB. */
const getSymbolFromUniqueId = (uid) => {
  if (!uid || typeof uid !== "string") return "";
  const u = String(uid).toUpperCase();
  const buy = u.indexOf("BUY");
  const sell = u.indexOf("SELL");
  let end = -1;
  if (buy >= 0 && sell >= 0) end = Math.min(buy, sell);
  else if (buy >= 0) end = buy;
  else if (sell >= 0) end = sell;
  if (end > 0) return String(uid).slice(0, end).replace(/[^A-Z0-9]/gi, "").toUpperCase() || "";
  return "";
};

const INDICATORS = [
  { key: "RSI@tv-basicstudies", label: "RSI-9" },
  { key: "MACD@tv-basicstudies", label: "MACD" },
  { key: "Volume@tv-basicstudies", label: "Volume" },
  { key: "CCI@tv-basicstudies", label: "CCI" },
];

const INFO_FIELDS_KEY = "singleTradeLiveView_infoFields";
const INTERVAL_ORDER_KEY = "singleTradeLiveView_intervalOrder";
const INFO_GRID_HEIGHT_KEY = "singleTradeLiveView_infoGridHeight";
const BACK_DATA_HEIGHT_KEY = "singleTradeLiveView_backDataHeight";
const CHART_HEIGHT_KEY = "singleTradeLiveView_chartHeight";

const INFO_LEFT_HEIGHT_KEY = "singleTradeLiveView_infoLeftHeight";
const BACK_LEFT_HEIGHT_KEY = "singleTradeLiveView_backLeftHeight";
const INFO_SPLIT_KEY = "singleTradeLiveView_infoSplitPercent";
const BACK_SPLIT_KEY = "singleTradeLiveView_backSplitPercent";
const INFO_SECTION_HEIGHT_KEY = "singleTradeLiveView_infoSectionHeight";
const BACK_SECTION_HEIGHT_KEY = "singleTradeLiveView_backSectionHeight";
const CHART_SECTION_HEIGHT_KEY = "singleTradeLiveView_chartSectionHeight";
const INFO_FIELD_ORDER_KEY = "singleTradeLiveView_infoFieldOrder";
const SECTION_ORDER_KEY = "singleTradeLiveView_sectionOrder";
const SIGNALS_VIEW_MODE_KEY = "singleTradeLiveView_signalsViewMode";
const SIGNAL_ALERT_RULES_KEY = "singleTradeLiveView_signalAlertRules";
const ALERT_RULE_GROUPS_KEY = "singleTradeLiveView_alertRuleGroups";
const MASTER_BLINK_COLOR_KEY = "singleTradeLiveView_masterBlinkColor";
const ACTIVE_RULE_BOOK_ID_KEY = "singleTradeLiveView_activeRuleBookId";
const LOCAL_RULE_BOOKS_KEY = "singleTradeLiveView_localRuleBooks";
const ACTIVE_LOCAL_RULE_BOOK_ID_KEY = "singleTradeLiveView_activeLocalRuleBookId";
const BINANCE_COLUMNS_ORDER_KEY = "singleTradeLiveView_binanceColumnsOrder";
const BINANCE_COLUMNS_VISIBILITY_KEY = "singleTradeLiveView_binanceColumnsVisibility";
const SECTION_IDS = ["information", "binanceData", "chart"];
const SECTION_LABELS = { information: "Information", binanceData: "Binance Data", chart: "Chart" };

const INTERVALS = ["5m", "15m", "1h", "4h"];
// Display order: current first, then prev, then prior (API summary is [prior, prev, current] = index 0,1,2)
const ROW_LABELS = ["current_row", "prev row", "prior row"];
const ROW_LABEL_TO_DATA_INDEX = { "prior row": 0, "prev row": 1, "current_row": 2 };

// Format signal name for display: show first + "..." + last,
// and if that would still look identical for multiple rows, fall back to full name
function formatSignalName(label, allLabels) {
  if (!label || label.length <= 14) return label;
  const prefixLen = 4;
  const suffixLen = 4;
  const extendedSuffixLen = 6; // Use more chars when prefix is shared
  
  const prefix = label.substring(0, prefixLen).toLowerCase();
  const similar = allLabels.filter((l) => l && l.toLowerCase().startsWith(prefix));
  
  if (similar.length > 1) {
    // Multiple names start the same - try first+...+extendedEnd
    const start = label.substring(0, prefixLen);
    const end = label.substring(label.length - extendedSuffixLen);
    const candidate = `${start}...${end}`;

    // If any other label would render to the same candidate, show full label instead
    const collisions = similar.filter((other) => {
      if (other === label) return false;
      const oEnd = other.substring(other.length - extendedSuffixLen);
      return `${start}...${oEnd}` === candidate;
    });

    if (collisions.length === 0) {
      return candidate;
    }

    // Names are still indistinguishable with start+end → show full label
    return label;
  }
  // Unique prefix - standard truncation
  const start = label.substring(0, prefixLen);
  const end = label.substring(label.length - suffixLen);
  return `${start}...${end}`;
}
const INTERVAL_GROUP_COLORS = [
  "bg-teal-100 dark:bg-teal-900/40",
  "bg-blue-100 dark:bg-blue-900/40",
  "bg-emerald-100 dark:bg-emerald-900/40",
  "bg-amber-100 dark:bg-amber-900/40",
];
const ROW_GROUP_COLORS = [
  "bg-teal-100 dark:bg-teal-900/40",
  "bg-blue-100 dark:bg-blue-900/40",
  "bg-amber-100 dark:bg-amber-900/40",
];

// Signals grid: only these rows (label = display, key = API response key)
const SIGNAL_ROWS = [
  { label: "HA_LOW", key: "ha_low" },
  { label: "HA_HIGH", key: "ha_high" },
  { label: "INST Signal", key: "INSTITUTIONAL_SIGNAL" },
  { label: "BB FLAT", key: "bb_flat_market" },
  { label: "BB FLAT SIGNAL", key: "bb_flat_signal" },
  { label: "RSI_9", key: "RSI_9" },
  { label: "Divergence", key: "RSI_DIVERGENCE" },
  { label: "DIVERGEN_SIGNAL_LIVE", key: "DIVERGEN_SIGNAL_LIVE" },
  { label: "RSI_DIVERGENCE_LIVE", key: "RSI_DIVERGENCE_LIVE" },
  { label: "TAKEACTION", key: "TAKEACTION" },
  { label: "CCI Exit Cross 9", key: "cci_exit_cross_9" },
  { label: "MACD Color Signal", key: "macd_color_signal" },
  { label: "CCI Entry State 100", key: "cci_entry_state_100" },
  { label: "CCI SMA 100", key: "cci_sma_100" },
  { label: "CCI Entry State 9", key: "cci_entry_state_9" },
  { label: "CCI SMA 9", key: "cci_sma_9" },
  { label: "cci_value_100", key: "cci_value_100" },
  { label: "cci_value_9", key: "cci_value_9" },
  { label: "Lower MACD Color Signa", key: "lower_macd_color_signal" },
  { label: "Andean Oscillator", key: "andean_oscillator" },
  { label: "Candle Henkin Color", key: "ha_color" },
  { label: "Candle Regular Color", key: "color" },
  { label: "EMA 5 8 Cross", key: "ema_5_8_cross" },
  { label: "ZLEMA Bullish Entry", key: "zlema_bullish_entry" },
  { label: "ZLEMA Bearish Entry", key: "zlema_bearish_entry" },
  { label: "Volume Ratio", key: "Volume_Ratio" },
  { label: "OB_SIGNAL", key: "OB_SIGNAL" },
  { label: "RG Candle Pattern", key: "candle_pattern_signal" },
  { label: "HK Candle Pattern", key: "henkin_candle_pattern_signal" },
  { label: "TDFI 2 EMA", key: "tdfi_state_2_ema" },
  { label: "TDFI State", key: "tdfi_state" },
  { label: "Two Pole MACD CrossOver", key: "two_pole_MACD_Cross_Up" },
  { label: "Total Change", key: "Total_Change" },
  { label: "BBW", key: "BBW" },
  { label: "BBW_Increasing", key: "BBW_Increasing" },
  { label: "BREAKOUT_SIGNAL", key: "BREAKOUT_SIGNAL" },
  { label: "FOLLOW_INST_BUY_OK", key: "FOLLOW_INST_BUY_OK" },
  { label: "FOLLOW_INST_SELL_OK", key: "FOLLOW_INST_SELL_OK" },
  { label: "breakout_entry", key: "breakout_entry" },
  { label: "ema_price_trend_signal", key: "ema_price_trend_signal" },
  { label: "ema_trend_100_14", key: "ema_trend_100_14" },
  { label: "exit_long_price_action", key: "exit_long_raw" },
  { label: "exit_short_price_action", key: "exit_short_raw" },
  { label: "price_trend_direction", key: "price_trend_direction" },
  { label: "stoch_7_3_3_cross_buy", key: "stoch_7_3_3_cross_buy" },
  { label: "stoch_7_3_3_cross_sell", key: "stoch_7_3_3_cross_sell" },
  { label: "stoch_7_3_3_overbought", key: "stoch_7_3_3_overbought" },
  { label: "stoch_7_3_3_oversold", key: "stoch_7_3_3_oversold" },
  { label: "price_vs_ha_open", key: "price_vs_ha_open" },
  { label: "swing_high", key: "swing_high" },
  { label: "swing_low", key: "swing_low" },
  { label: "swing_high_zone", key: "swing_high_zone" },
  { label: "volume_increasing", key: "volume_increasing" },
];

// Password is validated by the API (users table); no client-side check
const ACTION_LABELS = {
  execute: "Execute trade",
  endTrade: "End trade",
  autoPilot: "Auto-Pilot",
  hedge: "Hedge",
  setStopPrice: "Set stop price",
  addInvestment: "Add investment",
  clear: "Clear",
};

function ConfirmActionModal({
  open,
  onClose,
  actionType,
  requireAmount,
  amountLabel = "Amount",
  amountPlaceholder = "0",
  extraLabel,
  extraValue,
  onConfirm,
}) {
  const [step, setStep] = useState("password");
  const [password, setPassword] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [successMessage, setSuccessMessage] = useState("Success!");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const title = ACTION_LABELS[actionType] || actionType;
  const showAmountStep = requireAmount && step === "amount";
  const showPasswordStep = step === "password";
  const showSuccess = success;

  const reset = useCallback(() => {
    setStep("password");
    setPassword("");
    setAmount("");
    setError("");
    setSuccess(false);
    setSuccessMessage("Success!");
    setIsSubmitting(false);
  }, []);

  useEffect(() => {
    if (open) reset();
  }, [open, actionType, reset]);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  const validatePassword = () => {
    const p = (password || "").trim();
    if (!p) {
      setError("Enter password");
      return false;
    }
    setError("");
    return true;
  };

  const handlePasswordNext = () => {
    if (!validatePassword()) return;
    if (requireAmount) setStep("amount");
    else doConfirm();
  };

  const doConfirm = async () => {
    if (isSubmitting) return;
    setError("");
    setIsSubmitting(true);
    try {
      const payload = { password: (password || "").trim() };
      if (requireAmount) payload.amount = amount.trim();
      if (extraValue !== undefined) payload.extraValue = extraValue;
      const result = await (onConfirm && onConfirm(payload));
      const msg = (result && typeof result === "string") ? result : (result?.successMessage ?? "Success!");
      setSuccessMessage(msg);
      setSuccess(true);
      setTimeout(handleClose, 1500);
    } catch (e) {
      setError(e?.message || "Failed");
      setIsSubmitting(false);
    }
  };

  const handleAmountConfirm = () => {
    if (requireAmount && !(amount || "").trim()) {
      setError(`Enter ${amountLabel.toLowerCase()}`);
      return;
    }
    doConfirm();
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={handleClose}>
      <div
        className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-sm w-full shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-semibold text-lg mb-3">{title}</h3>
        {showSuccess && (
          <p className="text-green-600 dark:text-green-400 font-medium mb-4">{successMessage}</p>
        )}
        {!showSuccess && showPasswordStep && (
          <>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setError(""); }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handlePasswordNext();
                }
              }}
              placeholder="Password"
              className="w-full border-2 border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-[#333] text-[#222] dark:text-white mb-3"
              autoFocus
            />
            {extraLabel && extraValue != null && (
              <p className="text-sm text-gray-500 dark:text-white/90 mb-2">{extraLabel}: {extraValue}</p>
            )}
          </>
        )}
        {!showSuccess && showAmountStep && (
          <>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{amountLabel}</label>
            <input
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(e) => { setAmount(e.target.value); setError(""); }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleAmountConfirm();
                }
              }}
              placeholder={amountPlaceholder}
              className="w-full border-2 border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-[#333] text-[#222] dark:text-white mb-3"
              autoFocus
            />
          </>
        )}
        {error && <p className="text-red-600 dark:text-red-400 text-sm mb-2">{error}</p>}
        {!showSuccess && (
          <div className="flex gap-2 justify-end mt-4">
            <button type="button" onClick={handleClose} className="px-3 py-1.5 rounded-lg bg-gray-200 dark:bg-gray-700">
              Cancel
            </button>
            {showPasswordStep && (
              <button type="button" onClick={handlePasswordNext} disabled={isSubmitting} className="px-4 py-1.5 rounded-lg bg-teal-600 text-white disabled:opacity-50 disabled:cursor-not-allowed">
                {isSubmitting ? "…" : (requireAmount ? "Next" : "Confirm")}
              </button>
            )}
            {showAmountStep && (
              <>
                <button type="button" onClick={() => setStep("password")} disabled={isSubmitting} className="px-3 py-1.5 rounded-lg bg-gray-200 dark:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed">
                  Back
                </button>
                <button type="button" onClick={handleAmountConfirm} disabled={isSubmitting} className="px-4 py-1.5 rounded-lg bg-teal-600 text-white disabled:opacity-50 disabled:cursor-not-allowed">
                  {isSubmitting ? "…" : "Confirm"}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const ZOOM_KEYS = {
  infoLeft: "singleTradeLiveView_zoom_infoLeft",
  infoGrid: "singleTradeLiveView_zoom_infoGrid",
  backLeft: "singleTradeLiveView_zoom_backLeft",
  backButtons: "singleTradeLiveView_zoom_backButtons",
  backRight: "singleTradeLiveView_zoom_backRight",
  chart: "singleTradeLiveView_zoom_chart",
};
// Allow a wider zoom range so font/size adjustments are more noticeable
const ZOOM_CONFIG = { default: 100, min: 50, max: 350, step: 10 };

function InfoFieldsModal({ orderedKeys, allKeys, visibleKeys, setVisibleKeys, setFieldOrder, onClose }) {
  const [dragIndex, setDragIndex] = useState(null);
  const [overIndex, setOverIndex] = useState(null);
  const visible = visibleKeys == null ? new Set(allKeys) : visibleKeys;

  const handleDragStart = (e, index) => {
    setDragIndex(index);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
  };
  const handleDragOver = (e, index) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setOverIndex(index);
  };
  const handleDragLeave = () => setOverIndex(null);
  const handleDrop = (e, toIndex) => {
    e.preventDefault();
    setOverIndex(null);
    if (dragIndex == null) return;
    const fromIndex = dragIndex;
    setDragIndex(null);
    if (fromIndex === toIndex) return;
    const next = [...orderedKeys];
    const [removed] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, removed);
    setFieldOrder(next);
  };
  const handleDragEnd = () => {
    setDragIndex(null);
    setOverIndex(null);
  };

  const toggleVisible = (key) => {
    const next = new Set(visible);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setVisibleKeys(next);
  };
  const showAll = () => setVisibleKeys(new Set(allKeys));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-lg w-full shadow-xl max-h-[80vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-semibold text-lg mb-2">Information fields</h3>
        <p className="text-sm text-gray-500 dark:text-white/90 mb-4">
          Toggle visibility and drag to reorder. Only checked fields are shown.
        </p>
        <ul className="space-y-1">
          {orderedKeys.map((key, index) => (
            <li
              key={key}
              draggable
              onDragStart={(e) => handleDragStart(e, index)}
              onDragOver={(e) => handleDragOver(e, index)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, index)}
              onDragEnd={handleDragEnd}
              className={`flex items-center gap-2 py-1.5 px-2 rounded border cursor-grab active:cursor-grabbing ${
                overIndex === index ? "border-teal-500 bg-teal-500/10" : "border-transparent hover:bg-gray-100 dark:hover:bg-gray-800"
              } ${dragIndex === index ? "opacity-60" : ""}`}
            >
              <span className="text-gray-400 dark:text-white/70 select-none" title="Drag to reorder">⋮⋮</span>
              <input
                type="checkbox"
                id={`info_${key}`}
                checked={visible.has(key)}
                onChange={() => toggleVisible(key)}
              />
              <label htmlFor={`info_${key}`} className="cursor-pointer flex-1">{key.replace(/_/g, " ")}</label>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={showAll} className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700">
            Show all
          </button>
          <button type="button" onClick={onClose} className="px-4 py-2 rounded bg-teal-600 text-white">
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

function SectionOrderModal({ sectionOrder, setSectionOrder, onClose }) {
  const [dragIndex, setDragIndex] = useState(null);
  const [overIndex, setOverIndex] = useState(null);
  const dragIndexRef = useRef(null);

  const handleDragStart = (e, index) => {
    dragIndexRef.current = index;
    setDragIndex(index);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
    try {
      if (e.dataTransfer.setDragImage && e.currentTarget) {
        e.dataTransfer.setDragImage(e.currentTarget, 0, 0);
      }
    } catch (_) {}
  };
  const handleDragOver = (e, index) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    setOverIndex(index);
  };
  const handleDragLeave = () => setOverIndex(null);
  const handleDrop = (e, toIndex) => {
    e.preventDefault();
    e.stopPropagation();
    setOverIndex(null);
    const fromIndex = dragIndexRef.current ?? dragIndex;
    dragIndexRef.current = null;
    setDragIndex(null);
    if (fromIndex == null || fromIndex === toIndex) return;
    const next = [...sectionOrder];
    const [removed] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, removed);
    setSectionOrder(next);
  };
  const handleDragEnd = () => {
    dragIndexRef.current = null;
    setDragIndex(null);
    setOverIndex(null);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-md w-full shadow-xl"
        onClick={(e) => e.stopPropagation()}
        onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = "move"; }}
      >
        <h3 className="font-semibold text-lg mb-2">Section order</h3>
        <p className="text-sm text-gray-500 dark:text-white/90 mb-4">
          Drag to set the order of sections (top to bottom).
        </p>
        <ul
          className="space-y-1"
          onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = "move"; }}
        >
          {sectionOrder.map((id, index) => (
            <li
              key={id}
              draggable
              onDragStart={(e) => handleDragStart(e, index)}
              onDragOver={(e) => handleDragOver(e, index)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, index)}
              onDragEnd={handleDragEnd}
              className={`flex items-center gap-2 py-2.5 px-3 rounded border cursor-grab active:cursor-grabbing ${
                overIndex === index ? "border-teal-500 bg-teal-500/10" : "border-transparent hover:bg-gray-100 dark:hover:bg-gray-800"
              } ${dragIndex === index ? "opacity-60" : ""}`}
            >
              <span className="text-gray-400 dark:text-white/70 select-none" title="Drag to reorder">⋮⋮</span>
              <span className="font-medium flex-1">{SECTION_LABELS[id] || id}</span>
              <span className="flex gap-0.5">
                <button
                  type="button"
                  disabled={index === 0}
                  onClick={() => {
                    if (index === 0) return;
                    const next = [...sectionOrder];
                    [next[index - 1], next[index]] = [next[index], next[index - 1]];
                    setSectionOrder(next);
                  }}
                  className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                  title="Move up"
                  aria-label="Move up"
                >
                  ↑
                </button>
                <button
                  type="button"
                  disabled={index === sectionOrder.length - 1}
                  onClick={() => {
                    if (index >= sectionOrder.length - 1) return;
                    const next = [...sectionOrder];
                    [next[index], next[index + 1]] = [next[index + 1], next[index]];
                    setSectionOrder(next);
                  }}
                  className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                  title="Move down"
                  aria-label="Move down"
                >
                  ↓
                </button>
              </span>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex justify-end">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded bg-teal-600 text-white">
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

function BinanceColumnsModal({ columns, setColumns, visibility, setVisibility, onClose }) {
  const [dragIndex, setDragIndex] = useState(null);
  const [overIndex, setOverIndex] = useState(null);

  const handleDragStart = (e, index) => {
    setDragIndex(index);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
  };
  const handleDragOver = (e, index) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setOverIndex(index);
  };
  const handleDragLeave = () => setOverIndex(null);
  const handleDrop = (e, toIndex) => {
    e.preventDefault();
    setOverIndex(null);
    if (dragIndex == null) return;
    const fromIndex = dragIndex;
    setDragIndex(null);
    if (fromIndex === toIndex) return;
    const next = [...columns];
    const [removed] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, removed);
    setColumns(next);
  };
  const handleDragEnd = () => {
    setDragIndex(null);
    setOverIndex(null);
  };

  const setVisible = (col, value) => {
    setVisibility((prev) => ({ ...prev, [col]: value }));
  };
  const showAll = () => {
    setVisibility((prev) => {
      const next = { ...prev };
      columns.forEach((c) => (next[c] = true));
      return next;
    });
  };

  const list = columns.length ? columns : [];
  const baseLabels = list.map((col) =>
    col === "__actions__" ? "Actions" : col.replace(/([A-Z])/g, " $1").trim()
  );
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-2xl w-[90vw] shadow-xl max-h-[85vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-semibold text-xl mb-1">Binance columns</h3>
        <p className="text-sm text-gray-500 dark:text-white/90 mb-4">
          Drag to reorder; check or uncheck to show or hide columns.
        </p>
        <ul className="space-y-1 overflow-auto flex-1 min-h-0 pr-2">
          {list.map((col, index) => {
            const baseLabel = baseLabels[index];
            const label =
              col === "__actions__"
                ? baseLabel
                : formatSignalName(baseLabel, baseLabels);
            const visible = visibility[col] !== false;
            return (
              <li
                key={col}
                draggable
                onDragStart={(e) => handleDragStart(e, index)}
                onDragOver={(e) => handleDragOver(e, index)}
                onDragLeave={handleDragLeave}
                onDrop={(e) => handleDrop(e, index)}
                onDragEnd={handleDragEnd}
                className={`flex items-center gap-3 py-2.5 px-3 rounded border cursor-grab active:cursor-grabbing ${
                  overIndex === index ? "border-teal-500 bg-teal-500/10" : "border-transparent hover:bg-gray-100 dark:hover:bg-gray-800"
                } ${dragIndex === index ? "opacity-60" : ""}`}
              >
                <span className="text-gray-400 dark:text-white/70 select-none shrink-0" title="Drag to reorder">⋮⋮</span>
                <input
                  type="checkbox"
                  id={`binance_${col}`}
                  checked={visible}
                  onChange={() => setVisible(col, !visible)}
                  className="h-4 w-4 text-teal-600 shrink-0"
                />
                <label htmlFor={`binance_${col}`} className="cursor-pointer flex-1 font-medium truncate" title={label}>
                  {label}
                </label>
              </li>
            );
          })}
        </ul>
        <div className="mt-4 flex justify-end gap-2 shrink-0">
          <button type="button" onClick={showAll} className="px-4 py-2 rounded bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-100">
            Show all
          </button>
          <button type="button" onClick={onClose} className="px-4 py-2 rounded bg-teal-600 text-white">
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

function useZoomLevel(storageKey) {
  const [level, setLevel] = useState(() => {
    try {
      const v = localStorage.getItem(storageKey);
      if (v != null) {
        const n = parseInt(v, 10);
        if (!Number.isNaN(n)) return Math.max(ZOOM_CONFIG.min, Math.min(ZOOM_CONFIG.max, n));
      }
    } catch {}
    return ZOOM_CONFIG.default;
  });
  useEffect(() => {
    localStorage.setItem(storageKey, String(level));
  }, [storageKey, level]);
  const decrease = () => setLevel((l) => Math.max(ZOOM_CONFIG.min, l - ZOOM_CONFIG.step));
  const increase = () => setLevel((l) => Math.min(ZOOM_CONFIG.max, l + ZOOM_CONFIG.step));
  return [level, decrease, increase];
}

function ZoomControls({ onDecrease, onIncrease, current, label, className = "" }) {
  const atMin = current <= ZOOM_CONFIG.min;
  const atMax = current >= ZOOM_CONFIG.max;
  const btnClass = className || "min-w-[36px] min-h-[36px] flex items-center justify-center rounded-lg bg-white/20 hover:bg-white/30 disabled:opacity-40 text-sm font-bold transition-colors";
  return (
    <div className="flex items-center gap-1" title={`${label || "Zoom"} (${current}%)`}>
      <button type="button" onClick={onDecrease} disabled={atMin} aria-label="Zoom out font" className={btnClass}>
        A−
      </button>
      <button type="button" onClick={onIncrease} disabled={atMax} aria-label="Zoom in font" className={btnClass}>
        A+
      </button>
    </div>
  );
}

const SIZE_CONFIG = {
  infoGrid: { default: 280, min: 80, max: 1400, step: 40 },
  infoLeft: { default: 100, min: 40, max: 500, step: 20 },
  backData: { default: 100, min: 60, max: 1000, step: 32 },
  backLeft: { default: 60, min: 40, max: 400, step: 16 },
  chart: { default: 380, min: 120, max: 1400, step: 40 },
};

function useSectionSize(storageKey, config) {
  const [size, setSize] = useState(() => {
    try {
      const v = localStorage.getItem(storageKey);
      if (v != null) {
        const n = parseInt(v, 10);
        if (!Number.isNaN(n)) return Math.max(config.min, Math.min(config.max, n));
      }
    } catch {}
    return config.default;
  });
  useEffect(() => {
    localStorage.setItem(storageKey, String(size));
  }, [storageKey, size]);
  const setSizeClamped = useCallback(
    (v) => setSize((s) => Math.max(config.min, Math.min(config.max, typeof v === "function" ? v(s) : v))),
    [config.min, config.max]
  );
  return [size, setSizeClamped];
}

function HeightDragger({ value, min, max, onChange, label }) {
  const startRef = useRef({ y: 0, value: 0 });
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onMouseDown = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      startRef.current = { y: e.clientY, value };
      const onMove = (ev) => {
        ev.preventDefault();
        const dy = ev.clientY - startRef.current.y;
        const newVal = Math.round(Math.max(min, Math.min(max, startRef.current.value + dy)));
        onChangeRef.current(newVal);
        startRef.current = { y: ev.clientY, value: newVal };
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      document.body.style.cursor = "ns-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [value, min, max]
  );
  return (
    <div
      role="separator"
      aria-label={label || "Drag to resize height"}
      className="h-3 w-full cursor-ns-resize hover:bg-teal-500/50 bg-teal-600/70 flex-shrink-0 rounded-b flex items-center justify-center group select-none"
      title="Drag to resize height"
      onMouseDown={onMouseDown}
    >
      <span className="text-white/80 text-xs group-hover:text-white pointer-events-none">⋮</span>
    </div>
  );
}

function WidthDragger({ leftPercent, min = 20, max = 80, onChange, label }) {
  const startRef = useRef({ x: 0, value: 0 });
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onMouseDown = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      startRef.current = { x: e.clientX, value: leftPercent };
      const onMove = (ev) => {
        ev.preventDefault();
        const dx = ev.clientX - startRef.current.x;
        const deltaPercent = (dx / window.innerWidth) * 100;
        const newVal = Math.round(Math.max(min, Math.min(max, startRef.current.value + deltaPercent)));
        onChangeRef.current(newVal);
        startRef.current = { x: ev.clientX, value: newVal };
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      document.body.style.cursor = "ew-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [leftPercent, min, max]
  );
  return (
    <div
      role="separator"
      aria-label={label || "Drag to resize width"}
      className="w-3 min-w-[12px] cursor-ew-resize hover:bg-teal-500/50 bg-teal-600/70 flex-shrink-0 flex items-center justify-center self-stretch rounded select-none"
      title="Drag to resize columns"
      onMouseDown={onMouseDown}
    >
      <span className="text-white/80 text-xs pointer-events-none">⋮</span>
    </div>
  );
}

function stripHtml(str) {
  if (str == null) return "";
  const s = String(str);
  if (typeof document === "undefined") return s.replace(/<[^>]+>/g, "").trim();
  const div = document.createElement("div");
  div.innerHTML = s;
  return (div.textContent || "").trim();
}

function LiveTradeChartSection({
  tradePair,
  chartSize = { width: 500, height: 400 },
  alertRules,
  setAlertRules,
  alertRuleGroups,
  setAlertRuleGroups,
  masterBlinkColor,
  setMasterBlinkColor,
  showAlertSettings,
  setShowAlertSettings,
}) {
  const pair = tradePair != null ? String(tradePair) : "";
  const symbols = [getRobustSymbol(pair), "BTCUSDT"];
  const getSetting = (key, def) => {
    try {
      const v = localStorage.getItem(`chartGridSetting_${key}`);
      if (v !== null) return JSON.parse(v);
    } catch {}
    return def;
  };
  const defaultIndicators = ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies", "CCI@tv-basicstudies"];
  const [interval, setIntervalState] = useState(getSetting("interval", "15m"));
  // Default to showing all intervals so charts are visible immediately on first load
  const [showAllIntervals, setShowAllIntervals] = useState(getSetting("showAllIntervals", true));
  const [layout, setLayout] = useState(getSetting("layout", 2));
  const [intervalOrder, setIntervalOrder] = useState(() => {
    try {
      const v = localStorage.getItem(INTERVAL_ORDER_KEY);
      if (v) return JSON.parse(v);
    } catch {}
    return [...ALL_INTERVALS];
  });
  const [showIntervalOrderModal, setShowIntervalOrderModal] = useState(false);
  const [indicators, setIndicators] = useState(getSetting("indicators", defaultIndicators));
  const [source] = useState(getSetting("source", "tradingview"));
  const [chartReady, setChartReady] = useState(false);
  const importInputRef = useRef(null);
  const [bulkSignalKeys, setBulkSignalKeys] = useState(() =>
    SIGNAL_ROWS.map((r) => r.key)
  );
  const [bulkIntervals, setBulkIntervals] = useState(() => [...INTERVALS]);
  const [bulkRows, setBulkRows] = useState(() => [...ROW_LABELS]);
  const [bulkType, setBulkType] = useState("number");
  const [bulkBoolValue, setBulkBoolValue] = useState(true);
  const [bulkStringOperator, setBulkStringOperator] = useState("eq");
  const [bulkStringValue, setBulkStringValue] = useState("");
  const [bulkEnumValue, setBulkEnumValue] = useState("BUY");
  const [bulkNumberOperator, setBulkNumberOperator] = useState(">=");
  const [bulkNumberThreshold, setBulkNumberThreshold] = useState(0);
  const [ruleSortKey, setRuleSortKey] = useState("signalKey");
  const [bulkGroupName, setBulkGroupName] = useState("");
  const [bulkGroupColor, setBulkGroupColor] = useState("");
  const [editingGroupId, setEditingGroupId] = useState(null);
  const [serverRuleBooks, setServerRuleBooks] = useState([]);
  const [selectedRuleBookId, setSelectedRuleBookId] = useState(() => {
    try {
      const raw = localStorage.getItem(ACTIVE_RULE_BOOK_ID_KEY);
      if (!raw) return null;
      const parsed = parseInt(raw, 10);
      return Number.isFinite(parsed) ? parsed : null;
    } catch {
      return null;
    }
  });
  const [ruleBooksLoading, setRuleBooksLoading] = useState(false);
  const [ruleBooksError, setRuleBooksError] = useState("");
  const [localRuleBooks, setLocalRuleBooks] = useState(() => {
    try {
      const raw = localStorage.getItem(LOCAL_RULE_BOOKS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed?.books) ? parsed.books : [];
    } catch {
      return [];
    }
  });
  const [selectedLocalRuleBookId, setSelectedLocalRuleBookId] = useState(() => {
    try {
      return localStorage.getItem(ACTIVE_LOCAL_RULE_BOOK_ID_KEY) || null;
    } catch {
      return null;
    }
  });
  const sortedAlertRules = useMemo(() => {
    const sorted = [...(alertRules || [])];
    sorted.sort((a, b) => {
      const va = (a[ruleSortKey] ?? "").toString().toLowerCase();
      const vb = (b[ruleSortKey] ?? "").toString().toLowerCase();
      if (va < vb) return -1;
      if (va > vb) return 1;
      return 0;
    });
    return sorted;
  }, [alertRules, ruleSortKey]);

  const setInterval = (v) => setIntervalState(v);

  useEffect(() => {
    try {
      localStorage.setItem(INTERVAL_ORDER_KEY, JSON.stringify(intervalOrder));
    } catch {}
  }, [intervalOrder]);

  // --- Server-side rule books (load list when settings modal is opened) ---
  useEffect(() => {
    if (!showAlertSettings) return;
    if (serverRuleBooks && serverRuleBooks.length > 0) return;
    let cancelled = false;
    const loadRuleBooks = async () => {
      setRuleBooksLoading(true);
      setRuleBooksError("");
      try {
        const res = await fetch(api("/api/alert-rule-books"));
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.error || res.statusText || "Failed to load rule books");
        }
        if (!cancelled) {
          const list = Array.isArray(data.ruleBooks) ? data.ruleBooks : [];
          setServerRuleBooks(list);
        }
      } catch (e) {
        console.error("[RuleBooks] Load failed:", e);
        if (!cancelled) setRuleBooksError(e?.message || "Failed to load rule books");
      } finally {
        if (!cancelled) setRuleBooksLoading(false);
      }
    };
    loadRuleBooks();
    return () => {
      cancelled = true;
    };
  }, [showAlertSettings, serverRuleBooks]);

  const handleLoadRuleBook = useCallback(
    async (id) => {
      if (!id) return;
      try {
        const res = await fetch(api(`/api/alert-rule-books/${id}`));
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.error || res.statusText || "Failed to load rule book");
        }
        const payload = data.payload || {};
        let rules = Array.isArray(payload.rules) ? payload.rules : [];
        let groups = Array.isArray(payload.groups) ? payload.groups : [];
        const masterColor = payload.masterBlinkColor || masterBlinkColor || "#f97316";
        if (groups.length === 0 && rules.length > 0) {
          const defaultGroupId = "imported-" + Date.now();
          groups = [
            { id: defaultGroupId, name: "Imported", color: masterColor },
          ];
          rules = rules.map((r) => ({ ...r, groupId: defaultGroupId }));
        }
        setAlertRules(rules);
        setAlertRuleGroups(groups);
        setMasterBlinkColor(masterColor);
        setSelectedRuleBookId(data.id || id);
        try {
          localStorage.setItem(ACTIVE_RULE_BOOK_ID_KEY, String(data.id || id));
        } catch {}
      } catch (e) {
        console.error("[RuleBooks] Load book failed:", e);
        if (typeof window !== "undefined") {
          window.alert(e?.message || "Failed to load rule book");
        }
      }
    },
    [setAlertRules, setAlertRuleGroups, setMasterBlinkColor, masterBlinkColor]
  );

  const handleSaveRuleBook = useCallback(
    async (mode) => {
      try {
        if (!alertRules || !alertRules.length) {
          window.alert("No rules to save. Create some rules first.");
          return;
        }
        let name = "";
        let id = null;
        if (mode === "new") {
          name = window.prompt("Enter a name for this rule book:");
          if (!name || !name.trim()) return;
        } else if (mode === "update") {
          const current = serverRuleBooks.find((b) => b.id === selectedRuleBookId);
          if (!current) {
            window.alert("No rule book is selected to update.");
            return;
          }
          name = current.name;
          id = current.id;
        } else {
          return;
        }

        const payload = {
          type: "lab_single_trade_alert_rules",
          version: 2,
          createdAt: new Date().toISOString(),
          rules: alertRules || [],
          groups: alertRuleGroups || [],
          masterBlinkColor: masterBlinkColor || "#f97316",
        };

        const res = await fetch(api("/api/alert-rule-books"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id, name: name.trim(), payload }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          throw new Error(data.error || res.statusText || "Failed to save rule book");
        }
        // Refresh list and remember active id
        const saved = data.ruleBook;
        try {
          localStorage.setItem(ACTIVE_RULE_BOOK_ID_KEY, String(saved.id));
        } catch {}
        setSelectedRuleBookId(saved.id);
        // Reload list
        try {
          const listRes = await fetch(api("/api/alert-rule-books"));
          const listData = await listRes.json().catch(() => ({}));
          const list = Array.isArray(listData.ruleBooks) ? listData.ruleBooks : [];
          setServerRuleBooks(list);
        } catch (e2) {
          console.error("[RuleBooks] Reload list failed:", e2);
        }
        if (typeof window !== "undefined") {
          window.alert(mode === "new" ? "Rule book saved on server." : "Rule book updated on server.");
        }
      } catch (e) {
        console.error("[RuleBooks] Save failed:", e);
        if (typeof window !== "undefined") {
          window.alert(e?.message || "Failed to save rule book");
        }
      }
    },
    [alertRules, alertRuleGroups, masterBlinkColor, serverRuleBooks, selectedRuleBookId]
  );

  const persistLocalRuleBooks = useCallback((books) => {
    try {
      localStorage.setItem(LOCAL_RULE_BOOKS_KEY, JSON.stringify({ books }));
    } catch (_) {}
  }, []);

  const handleSaveLocalRuleBook = useCallback(
    (mode) => {
      if (!alertRules || !alertRules.length) {
        window.alert("No rules to save. Create some rules first.");
        return;
      }
      let name = "";
      let id = null;
      if (mode === "new") {
        name = window.prompt("Enter a name for this rule book (saved on this device):");
        if (!name || !name.trim()) return;
        id = "local_" + Date.now();
      } else if (mode === "update") {
        const current = localRuleBooks.find((b) => b.id === selectedLocalRuleBookId);
        if (!current) {
          window.alert("No local rule book is selected to update.");
          return;
        }
        name = current.name;
        id = current.id;
      } else return;

      const book = {
        id,
        name: name.trim(),
        createdAt: new Date().toISOString(),
        rules: alertRules || [],
        groups: alertRuleGroups || [],
        masterBlinkColor: masterBlinkColor || "#f97316",
      };
      const nextBooks =
        mode === "new"
          ? [...localRuleBooks, book]
          : localRuleBooks.map((b) => (b.id === id ? book : b));
      setLocalRuleBooks(nextBooks);
      persistLocalRuleBooks(nextBooks);
      setSelectedLocalRuleBookId(id);
      try {
        localStorage.setItem(ACTIVE_LOCAL_RULE_BOOK_ID_KEY, String(id));
      } catch {}
      if (typeof window !== "undefined") {
        window.alert(mode === "new" ? "Rule book saved on this device." : "Rule book updated on this device.");
      }
    },
    [alertRules, alertRuleGroups, masterBlinkColor, localRuleBooks, selectedLocalRuleBookId, persistLocalRuleBooks]
  );

  const handleLoadLocalRuleBook = useCallback(
    (id) => {
      if (!id) return;
      const book = localRuleBooks.find((b) => b.id === id);
      if (!book) return;
      let rules = Array.isArray(book.rules) ? book.rules : [];
      let groups = Array.isArray(book.groups) ? book.groups : [];
      if (groups.length === 0 && rules.length > 0) {
        const defaultGroupId = "imported-" + Date.now();
        groups = [
          {
            id: defaultGroupId,
            name: "Imported",
            color: book.masterBlinkColor && /^#[0-9A-Fa-f]{6}$/.test(book.masterBlinkColor) ? book.masterBlinkColor : "#f97316",
          },
        ];
        rules = rules.map((r) => ({ ...r, groupId: defaultGroupId }));
      }
      setAlertRules(rules);
      setAlertRuleGroups(groups);
      setMasterBlinkColor(book.masterBlinkColor && /^#[0-9A-Fa-f]{6}$/.test(book.masterBlinkColor) ? book.masterBlinkColor : "#f97316");
      setSelectedLocalRuleBookId(id);
      try {
        localStorage.setItem(ACTIVE_LOCAL_RULE_BOOK_ID_KEY, String(id));
      } catch {}
    },
    [localRuleBooks, setAlertRules, setAlertRuleGroups, setMasterBlinkColor]
  );

  const handleExportAlertRules = useCallback(() => {
    if (typeof window === "undefined" || !window.document) return;
    try {
      const payload = {
        type: "lab_single_trade_alert_rules",
        version: 2,
        createdAt: new Date().toISOString(),
        rules: alertRules || [],
        groups: alertRuleGroups || [],
        masterBlinkColor: masterBlinkColor || "#f97316",
      };
      const json = JSON.stringify(payload, null, 2);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ts = new Date().toISOString().replace(/[:.]/g, "-");
      a.download = `lab-alert-rules-${ts}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("[AlertRules] Export failed:", e);
      if (typeof window !== "undefined") {
        window.alert("Failed to export rules. See console for details.");
      }
    }
  }, [alertRules, alertRuleGroups, masterBlinkColor]);

  const handleImportAlertRulesClick = useCallback(() => {
    if (importInputRef.current) {
      importInputRef.current.value = "";
      importInputRef.current.click();
    }
  }, []);

  const handleImportAlertRulesFile = useCallback(
    (event) => {
      try {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (e) => {
          try {
            const text = String(e.target?.result || "");
            const parsed = JSON.parse(text);
            const rules = Array.isArray(parsed)
              ? parsed
              : Array.isArray(parsed?.rules)
                ? parsed.rules
                : null;
            if (!rules) {
              window.alert("Invalid script file: expected an array of rules.");
              return;
            }
            let groups = Array.isArray(parsed?.groups) ? parsed.groups : [];
            let rulesToSet = rules;
            if (groups.length === 0) {
              const defaultGroupId = "imported-" + Date.now();
              const defaultGroup = {
                id: defaultGroupId,
                name: "Imported",
                color: parsed?.masterBlinkColor && /^#[0-9A-Fa-f]{6}$/.test(parsed.masterBlinkColor) ? parsed.masterBlinkColor : "#f97316",
              };
              groups = [defaultGroup];
              rulesToSet = rules.map((r) => ({ ...r, groupId: defaultGroupId }));
            } else {
              const groupIds = new Set(groups.map((g) => g.id));
              rulesToSet = rules.map((r) => {
                if (r.groupId && groupIds.has(r.groupId)) return r;
                const firstGroupId = groups[0]?.id;
                return { ...r, groupId: firstGroupId || r.groupId };
              });
            }
            setAlertRules(rulesToSet);
            setAlertRuleGroups(groups);
            if (parsed?.masterBlinkColor && /^#[0-9A-Fa-f]{6}$/.test(parsed.masterBlinkColor)) {
              setMasterBlinkColor(parsed.masterBlinkColor);
            }
          } catch (err) {
            console.error("[AlertRules] Import parse error:", err);
            window.alert("Failed to parse script file. See console for details.");
          }
        };
        reader.readAsText(file);
      } catch (err) {
        console.error("[AlertRules] Import failed:", err);
        if (typeof window !== "undefined") {
          window.alert("Failed to import rules. See console for details.");
        }
      }
    },
    [setAlertRules, setAlertRuleGroups, setMasterBlinkColor]
  );

  useEffect(() => {
    try {
      localStorage.setItem("chartGridSetting_interval", JSON.stringify(interval));
      localStorage.setItem("chartGridSetting_showAllIntervals", JSON.stringify(showAllIntervals));
      localStorage.setItem("chartGridSetting_layout", JSON.stringify(layout));
      localStorage.setItem("chartGridSetting_indicators", JSON.stringify(indicators));
    } catch {}
  }, [interval, showAllIntervals, layout, indicators]);

  const intervalsToShow = showAllIntervals ? intervalOrder : [interval];

  // Only recreate charts when these actual values change (not on every parent re-render).
  // Using primitives/stable keys avoids effect running when unrelated state (section order,
  // zoom, split %, etc.) changes in the parent.
  const chartHeight = chartSize?.height ?? 400;
  const chartWidth = chartSize?.width ?? 500;
  const intervalOrderKey = intervalOrder.join(",");
  const symbolsKey = symbols.join(",");

  useEffect(() => {
    // Create / refresh TradingView widgets when source, interval, indicators, etc. change.
    if (source !== "tradingview") {
      setChartReady(true);
      return;
    }
    setChartReady(false);
    const list = showAllIntervals ? intervalOrder : [interval];
    const pairs = [];
    symbols.forEach((symbol) => {
      list.forEach((intv) => pairs.push({ symbol, intv }));
    });

    const buildCharts = () => {
      if (typeof window === "undefined" || !window.TradingView) {
        setChartReady(true);
        return;
      }
      pairs.forEach(({ symbol, intv }) => {
        const safeIntv = (intv && String(intv).replace(/[^a-z0-9]/gi, "_")) || "15m";
        const cid = `single_tv_${symbol}_${safeIntv}`;
        const container = document.getElementById(cid);
        if (!container) return;
        try {
          container.innerHTML = "";
          new window.TradingView.widget({
            container_id: cid,
            autosize: true,
            symbol: `BINANCE:${symbol}PERP`,
            interval: intervalMap[intv] || "15",
            timezone: "Etc/UTC",
            theme: "dark",
            style: "8",
            locale: "en",
            studies: indicators,
            overrides: {
              "volumePaneSize": indicators.includes("Volume@tv-basicstudies") ? "medium" : "0",
              "paneProperties.topMargin": 10,
              "paneProperties.bottomMargin": 15,
              "paneProperties.rightMargin": 20,
              "scalesProperties.fontSize": 11,
            },
            studies_overrides: {
              "RSI@tv-basicstudies.length": 9,
            },
            hide_side_toolbar: false,
            allow_symbol_change: false,
            details: true,
            withdateranges: true,
            hideideas: true,
            toolbar_bg: "#222",
            height: chartHeight,
            width: chartWidth,
          });
        } catch (err) {
          console.warn("[Chart] Widget create error for", cid, err?.message || err);
        }
      });
      setChartReady(true);
    };

    // Ensure script is loaded; buildCharts will run once TradingView is ready.
    loadTradingViewScript(buildCharts);

    return () => {
      setChartReady(true);
    };
  }, [source, interval, showAllIntervals, intervalOrderKey, indicators, layout, symbolsKey, chartHeight, chartWidth]);

  return (
    <div className="bg-[#111] rounded-lg p-4 text-white">
      <div className="flex flex-wrap items-center gap-4 mb-4">
        <label>
          Interval:
          <select
            value={interval}
            onChange={(e) => setInterval(e.target.value)}
            className="ml-2 border rounded px-2 py-1 bg-[#222] text-white"
          >
            {ALL_INTERVALS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => setShowAllIntervals((s) => !s)}
          className={`px-3 py-1 rounded ${showAllIntervals ? "bg-amber-600" : "bg-[#333]"} hover:opacity-90`}
        >
          Show all intervals
        </button>
        <label>
          Layout:
          <select
            value={layout}
            onChange={(e) => setLayout(Number(e.target.value))}
            className="ml-2 border rounded px-2 py-1 bg-[#222] text-white"
          >
            <option value={1}>1 per row</option>
            <option value={2}>2 per row</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => setShowIntervalOrderModal(true)}
          className="px-3 py-1 rounded bg-[#333] hover:bg-[#444]"
        >
          ⚙️ Interval order
        </button>
        {INDICATORS.map((ind) => (
          <label key={ind.key} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={indicators.includes(ind.key)}
              onChange={(e) => {
                setIndicators((prev) =>
                  e.target.checked ? [...prev, ind.key] : prev.filter((i) => i !== ind.key)
                );
              }}
            />
            <span>{ind.label}</span>
          </label>
        ))}
      </div>

      {showIntervalOrderModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowIntervalOrderModal(false)}>
          <div className="bg-[#222] rounded-lg p-4 max-w-md w-full shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-semibold mb-2">Interval order (top to bottom)</h3>
            <p className="text-sm text-gray-400 mb-2">Reorder which interval appears first when &quot;Show all intervals&quot; is on.</p>
            <div className="flex flex-col gap-1 mt-2">
              {intervalOrder.map((intv, i) => (
                <div key={intv} className="flex items-center gap-2">
                  <span className="text-gray-500 w-6">{i + 1}.</span>
                  <span className="flex-1">{intv}</span>
                  <button
                    type="button"
                    disabled={i === 0}
                    onClick={() => {
                      const next = [...intervalOrder];
                      const [removed] = next.splice(i, 1);
                      next.splice(i - 1, 0, removed);
                      setIntervalOrder(next);
                    }}
                    className="px-2 py-0.5 rounded bg-[#333] disabled:opacity-40 text-sm"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    disabled={i === intervalOrder.length - 1}
                    onClick={() => {
                      const next = [...intervalOrder];
                      const [removed] = next.splice(i, 1);
                      next.splice(i + 1, 0, removed);
                      setIntervalOrder(next);
                    }}
                    className="px-2 py-0.5 rounded bg-[#333] disabled:opacity-40 text-sm"
                  >
                    ↓
                  </button>
                </div>
              ))}
            </div>
            <div className="flex justify-end mt-3">
              <button type="button" onClick={() => setShowIntervalOrderModal(false)} className="px-3 py-1 rounded bg-teal-600">
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {showAlertSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
          <div className="bg-[#111] text-white rounded-2xl shadow-2xl max-w-5xl w-[96%] max-h-[90vh] overflow-auto p-4 sm:p-6 border border-violet-700/60">
            <div className="flex items-center justify-between mb-4 gap-3">
              <h2 className="text-lg sm:text-xl font-semibold text-violet-200">
                Signal alert settings
              </h2>
              <button
                type="button"
                onClick={() => setShowAlertSettings(false)}
                className="px-2 py-1 rounded-lg bg-gray-700 hover:bg-gray-600 text-sm"
              >
                Close
              </button>
            </div>
            <p className="text-xs sm:text-sm text-gray-300 mb-3">
              Configure when a cell in the signals table should blink (like the Auto-Pilot button). Each rule matches a{" "}
              <span className="font-semibold text-violet-200">Signal</span>,{" "}
              <span className="font-semibold text-violet-200">Interval</span> and{" "}
              <span className="font-semibold text-violet-200">Candle row</span> (current / prev / prior).
            </p>
            {/* Local rule books (no login required) */}
            <div className="mb-4 p-3 rounded-xl bg-[#181818] border border-emerald-700/50 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-emerald-200">Rule books (saved on this device)</span>
                <select
                  className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-[11px] min-w-[160px]"
                  value={selectedLocalRuleBookId || ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (!v) {
                      setSelectedLocalRuleBookId(null);
                      try {
                        localStorage.removeItem(ACTIVE_LOCAL_RULE_BOOK_ID_KEY);
                      } catch {}
                      return;
                    }
                    setSelectedLocalRuleBookId(v);
                    handleLoadLocalRuleBook(v);
                  }}
                >
                  <option value="">(None selected)</option>
                  {localRuleBooks.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <button
                  type="button"
                  className="px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600"
                  onClick={() => handleSaveLocalRuleBook("new")}
                >
                  Save as new (this device)
                </button>
                <button
                  type="button"
                  className="px-2 py-1 rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed"
                  disabled={!selectedLocalRuleBookId}
                  onClick={() => handleSaveLocalRuleBook("update")}
                >
                  Update selected (this device)
                </button>
                <span className="text-[11px] text-gray-400">
                  Saved in this browser only. Works without logging in.
                </span>
              </div>
            </div>
            {/* Server-side rule books (requires login) */}
            <div className="mb-4 p-3 rounded-xl bg-[#181818] border border-violet-700/60 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-violet-200">Rule books (saved on server)</span>
                <select
                  className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-[11px] min-w-[160px]"
                  value={selectedRuleBookId || ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (!v) {
                      setSelectedRuleBookId(null);
                      try {
                        localStorage.removeItem(ACTIVE_RULE_BOOK_ID_KEY);
                      } catch {}
                      return;
                    }
                    const id = parseInt(v, 10);
                    if (Number.isFinite(id)) {
                      setSelectedRuleBookId(id);
                      handleLoadRuleBook(id);
                    }
                  }}
                >
                  <option value="">(None selected)</option>
                  {serverRuleBooks.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
                {ruleBooksLoading && (
                  <span className="text-[11px] text-gray-400">Loading…</span>
                )}
                {ruleBooksError && (
                  <span className="text-[11px] text-amber-400">
                    {ruleBooksError}
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <button
                  type="button"
                  className="px-2 py-1 rounded bg-violet-700 hover:bg-violet-600"
                  onClick={() => handleSaveRuleBook("new")}
                >
                  Save as new (server)
                </button>
                <button
                  type="button"
                  className="px-2 py-1 rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed"
                  disabled={!selectedRuleBookId}
                  onClick={() => handleSaveRuleBook("update")}
                >
                  Update selected (server)
                </button>
                <span className="text-[11px] text-gray-400">
                  Requires login. Use &quot;Saved on this device&quot; above if you see Not logged in.
                </span>
              </div>
            </div>
            {/* Master blink color */}
            <div className="mb-4 p-3 rounded-xl bg-[#181818] border border-violet-700/60 flex flex-wrap items-center gap-3">
              <span className="text-xs font-semibold text-violet-200">Master blink color</span>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={masterBlinkColor || "#f97316"}
                  onChange={(e) => setMasterBlinkColor(e.target.value)}
                  className="w-10 h-8 rounded border border-gray-600 cursor-pointer bg-[#111]"
                  title="Color for all blinking cells (unless overridden by group or rule)"
                />
                <input
                  type="text"
                  value={masterBlinkColor || "#f97316"}
                  onChange={(e) => {
                    const v = e.target.value.trim();
                    if (/^#[0-9A-Fa-f]{6}$/.test(v) || v === "") setMasterBlinkColor(v || "#f97316");
                  }}
                  className="w-24 bg-[#111] border border-gray-700 rounded px-2 py-1 text-[11px] font-mono"
                  placeholder="#f97316"
                />
              </div>
              <span className="text-[11px] text-gray-400">Default color for all alert cells. Groups and rules can override.</span>
            </div>
            {/* Bulk creator: select many signals / intervals / rows at once */}
            <div className="mb-4 p-3 rounded-xl bg-[#181818] border border-violet-700/60 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-semibold text-violet-200">
                    Bulk create rules (multi-select)
                  </span>
                  <div className="flex items-center gap-2 mt-0.5">
                    <input
                      type="text"
                      placeholder="Group name (optional)"
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-[11px] w-56"
                      value={bulkGroupName}
                      onChange={(e) => setBulkGroupName(e.target.value)}
                    />
                    <span className="text-[10px] text-gray-400 whitespace-nowrap">Group color:</span>
                    <input
                      type="color"
                      value={bulkGroupColor || "#f97316"}
                      onChange={(e) => setBulkGroupColor(e.target.value)}
                      className="w-8 h-7 rounded border border-gray-600 cursor-pointer bg-[#111]"
                      title="Blink color for this group"
                    />
                    <input
                      type="text"
                      value={bulkGroupColor || ""}
                      onChange={(e) => {
                        const v = e.target.value.trim();
                        if (/^#[0-9A-Fa-f]{6}$/.test(v) || v === "") setBulkGroupColor(v);
                      }}
                      className="w-20 bg-[#111] border border-gray-700 rounded px-1 py-0.5 text-[10px] font-mono"
                      placeholder="optional"
                    />
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {editingGroupId && (
                    <span className="text-[11px] text-amber-300">
                      Editing group
                    </span>
                  )}
                  <select
                    className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs"
                    value={bulkType}
                    onChange={(e) => {
                      const t = e.target.value;
                      setBulkType(t);
                      // Reset defaults when switching type so enum/text make sense
                      if (t === "buy_sell") setBulkEnumValue("BUY");
                      else if (t === "inc_dec") setBulkEnumValue("INCREASING");
                      else if (t === "bull_bear") setBulkEnumValue("BULL");
                      else if (t === "red_green") setBulkEnumValue("GREEN");
                      else if (t === "trend_3") setBulkEnumValue("bull_trending");
                    }}
                  >
                    <option value="number">Number</option>
                    <option value="boolean">True / False</option>
                    <option value="string">Text (any)</option>
                    <option value="buy_sell">Buy / Sell / None</option>
                    <option value="inc_dec">Increasing / Decreasing / None</option>
                    <option value="bull_bear">Bull / Bear / None</option>
                    <option value="red_green">Red / Green / None</option>
                    <option value="trend_3">Bull_trending / Flat / Bear_trending</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-[11px]">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-semibold text-gray-200">Signals</span>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        className="px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600"
                        onClick={() => setBulkSignalKeys(SIGNAL_ROWS.map((r) => r.key))}
                      >
                        All
                      </button>
                      <button
                        type="button"
                        className="px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600"
                        onClick={() => setBulkSignalKeys([])}
                      >
                        None
                      </button>
                    </div>
                  </div>
                  <div className="max-h-40 overflow-auto space-y-0.5 pr-1">
                    {SIGNAL_ROWS.map((r) => (
                      <label key={r.key} className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          className="h-3 w-3"
                          checked={bulkSignalKeys.includes(r.key)}
                          onChange={() =>
                            setBulkSignalKeys((prev) =>
                              prev.includes(r.key)
                                ? prev.filter((k) => k !== r.key)
                                : [...prev, r.key]
                            )
                          }
                        />
                        <span className="truncate">{r.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-semibold text-gray-200">Intervals</span>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        className="px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600"
                        onClick={() => setBulkIntervals([...INTERVALS])}
                      >
                        All
                      </button>
                      <button
                        type="button"
                        className="px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600"
                        onClick={() => setBulkIntervals([])}
                      >
                        None
                      </button>
                    </div>
                  </div>
                  <div className="space-y-0.5">
                    {INTERVALS.map((iv) => (
                      <label key={iv} className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          className="h-3 w-3"
                          checked={bulkIntervals.includes(iv)}
                          onChange={() =>
                            setBulkIntervals((prev) =>
                              prev.includes(iv)
                                ? prev.filter((v) => v !== iv)
                                : [...prev, iv]
                            )
                          }
                        />
                        <span>{iv}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-semibold text-gray-200">Candle rows</span>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        className="px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600"
                        onClick={() => setBulkRows([...ROW_LABELS])}
                      >
                        All
                      </button>
                      <button
                        type="button"
                        className="px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600"
                        onClick={() => setBulkRows([])}
                      >
                        None
                      </button>
                    </div>
                  </div>
                  <div className="space-y-0.5">
                    {ROW_LABELS.map((lbl) => (
                      <label key={lbl} className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          className="h-3 w-3"
                          checked={bulkRows.includes(lbl)}
                          onChange={() =>
                            setBulkRows((prev) =>
                              prev.includes(lbl)
                                ? prev.filter((v) => v !== lbl)
                                : [...prev, lbl]
                            )
                          }
                        />
                        <span>{lbl}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
              {/* Bulk value/condition */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-[11px]">
                {bulkType === "boolean" ? (
                  <div className="flex flex-col gap-1">
                    <span className="uppercase tracking-wide text-gray-400">
                      Boolean value
                    </span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                      value={bulkBoolValue ? "true" : "false"}
                      onChange={(e) => setBulkBoolValue(e.target.value === "true")}
                    >
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  </div>
                ) : bulkType === "string" ? (
                  <>
                    <div className="flex flex-col gap-1">
                      <span className="uppercase tracking-wide text-gray-400">
                        Condition
                      </span>
                      <select
                        className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                        value={bulkStringOperator}
                        onChange={(e) => setBulkStringOperator(e.target.value)}
                      >
                        <option value="eq">= equals</option>
                        <option value="neq">≠ not equal</option>
                        <option value="contains">contains</option>
                        <option value="not_contains">not contains</option>
                        <option value="starts_with">starts with</option>
                        <option value="ends_with">ends with</option>
                      </select>
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="uppercase tracking-wide text-gray-400">
                        Text
                      </span>
                      <input
                        type="text"
                        className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                        value={bulkStringValue}
                        onChange={(e) => setBulkStringValue(e.target.value)}
                      />
                    </div>
                  </>
                ) : bulkType === "buy_sell" ? (
                  <div className="flex flex-col gap-1">
                    <span className="uppercase tracking-wide text-gray-400">
                      Value
                    </span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                      value={bulkEnumValue}
                      onChange={(e) => setBulkEnumValue(e.target.value)}
                    >
                      <option value="BUY">BUY</option>
                      <option value="SELL">SELL</option>
                      <option value="NONE">NONE</option>
                    </select>
                  </div>
                ) : bulkType === "inc_dec" ? (
                  <div className="flex flex-col gap-1">
                    <span className="uppercase tracking-wide text-gray-400">
                      Value
                    </span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                      value={bulkEnumValue}
                      onChange={(e) => setBulkEnumValue(e.target.value)}
                    >
                      <option value="INCREASING">INCREASING</option>
                      <option value="DECREASING">DECREASING</option>
                      <option value="NONE">NONE</option>
                    </select>
                  </div>
                ) : bulkType === "bull_bear" ? (
                  <div className="flex flex-col gap-1">
                    <span className="uppercase tracking-wide text-gray-400">
                      Value
                    </span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                      value={bulkEnumValue}
                      onChange={(e) => setBulkEnumValue(e.target.value)}
                    >
                      <option value="BULL">BULL</option>
                      <option value="BEAR">BEAR</option>
                      <option value="NONE">NONE</option>
                    </select>
                  </div>
                ) : bulkType === "red_green" ? (
                  <div className="flex flex-col gap-1">
                    <span className="uppercase tracking-wide text-gray-400">
                      Value
                    </span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                      value={bulkEnumValue}
                      onChange={(e) => setBulkEnumValue(e.target.value)}
                    >
                      <option value="GREEN">GREEN</option>
                      <option value="RED">RED</option>
                      <option value="NONE">NONE</option>
                    </select>
                  </div>
                ) : bulkType === "trend_3" ? (
                  <div className="flex flex-col gap-1">
                    <span className="uppercase tracking-wide text-gray-400">
                      Value
                    </span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                      value={bulkEnumValue}
                      onChange={(e) => setBulkEnumValue(e.target.value)}
                    >
                      <option value="bull_trending">bull_trending</option>
                      <option value="flat">flat</option>
                      <option value="bear_trending">bear_trending</option>
                    </select>
                  </div>
                ) : (
                  <>
                    <div className="flex flex-col gap-1">
                      <span className="uppercase tracking-wide text-gray-400">
                        Condition
                      </span>
                      <select
                        className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                        value={bulkNumberOperator}
                        onChange={(e) => setBulkNumberOperator(e.target.value)}
                      >
                        <option value=">">&gt;</option>
                        <option value=">=">&gt;=</option>
                        <option value="<">&lt;</option>
                        <option value="<=">&lt;=</option>
                        <option value="==">=</option>
                        <option value="!=">≠</option>
                      </select>
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="uppercase tracking-wide text-gray-400">
                        Number
                      </span>
                      <input
                        type="number"
                        className="bg-[#111] border border-gray-700 rounded px-2 py-1"
                        value={bulkNumberThreshold}
                        onChange={(e) => setBulkNumberThreshold(e.target.value)}
                      />
                    </div>
                  </>
                )}
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-xs font-medium"
                  onClick={() => {
                    if (!bulkSignalKeys.length || !bulkIntervals.length || !bulkRows.length) {
                      window.alert("Select at least one Signal, Interval and Candle row.");
                      return;
                    }
                    const now = Date.now();
                    const groupId =
                      editingGroupId ||
                      `grp_${now}_${Math.random().toString(36).slice(2, 8)}`;
                    const newRules = [];
                    bulkSignalKeys.forEach((signalKey) => {
                      bulkIntervals.forEach((interval) => {
                        bulkRows.forEach((rowLabel) => {
                          const base = {
                            id: `${now}_${signalKey}_${interval}_${rowLabel}_${Math.random()
                              .toString(36)
                              .slice(2, 8)}`,
                            groupId,
                            signalKey,
                            interval,
                            rowLabel,
                            type: bulkType,
                          };
                          if (bulkType === "boolean") {
                            newRules.push({ ...base, boolValue: bulkBoolValue });
                          } else if (bulkType === "string") {
                            newRules.push({
                              ...base,
                              operator: bulkStringOperator,
                              stringValue: bulkStringValue,
                            });
                          } else if (
                            bulkType === "buy_sell" ||
                            bulkType === "inc_dec" ||
                            bulkType === "bull_bear" ||
                            bulkType === "red_green" ||
                            bulkType === "trend_3"
                          ) {
                            newRules.push({ ...base, enumValue: bulkEnumValue });
                          } else {
                            newRules.push({
                              ...base,
                              operator: bulkNumberOperator,
                              threshold: bulkNumberThreshold,
                            });
                          }
                        });
                      });
                    });

                    const groupName =
                      bulkGroupName && bulkGroupName.trim().length
                        ? bulkGroupName.trim()
                        : `Group ${alertRuleGroups.length + (editingGroupId ? 0 : 1)}`;

                    const groupColor = (bulkGroupColor && /^#[0-9A-Fa-f]{6}$/.test(bulkGroupColor)) ? bulkGroupColor : null;
                    if (editingGroupId) {
                      // Replace existing group's rules
                      setAlertRules((prev) => [
                        ...prev.filter((r) => r.groupId !== editingGroupId),
                        ...newRules,
                      ]);
                      setAlertRuleGroups((prev) =>
                        prev.map((g) =>
                          g.id === editingGroupId
                            ? {
                                ...g,
                                name: groupName,
                                color: groupColor,
                                type: bulkType,
                                signalKeys: [...bulkSignalKeys],
                                intervals: [...bulkIntervals],
                                rows: [...bulkRows],
                                boolValue: bulkBoolValue,
                                stringOperator: bulkStringOperator,
                                stringValue: bulkStringValue,
                                enumValue: bulkEnumValue,
                                numberOperator: bulkNumberOperator,
                                numberThreshold: bulkNumberThreshold,
                              }
                            : g
                        )
                      );
                    } else {
                      setAlertRules((prev) => [...prev, ...newRules]);
                      setAlertRuleGroups((prev) => [
                        ...prev,
                        {
                          id: groupId,
                          name: groupName,
                          color: groupColor,
                          type: bulkType,
                          signalKeys: [...bulkSignalKeys],
                          intervals: [...bulkIntervals],
                          rows: [...bulkRows],
                          boolValue: bulkBoolValue,
                          stringOperator: bulkStringOperator,
                          stringValue: bulkStringValue,
                          enumValue: bulkEnumValue,
                          numberOperator: bulkNumberOperator,
                          numberThreshold: bulkNumberThreshold,
                        },
                      ]);
                    }
                    setEditingGroupId(null);
                  }}
                >
                  {editingGroupId ? "Update group" : "Create rules"}
                </button>
              </div>
            </div>

            {/* Group list */}
            {alertRuleGroups && alertRuleGroups.length > 0 && (
              <div className="mb-3 text-[11px] space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-gray-200">
                    Groups ({alertRuleGroups.length})
                  </span>
                </div>
                <div className="space-y-1">
                  {alertRuleGroups.map((g) => {
                    const total =
                      (g.signalKeys?.length || 0) *
                      (g.intervals?.length || 0) *
                      (g.rows?.length || 0);
                    const groupRules = (alertRules || []).filter((r) => r.groupId === g.id);
                    const groupColor = (g.color && /^#[0-9A-Fa-f]{6}$/.test(g.color)) ? g.color : null;
                    const hasRuleColorOverrides = groupRules.some((r) => r.color != null && r.color !== groupColor);
                    return (
                      <div
                        key={g.id}
                        className="flex items-center justify-between bg-[#181818] border border-gray-700 rounded-lg px-2 py-1.5"
                      >
                        <div className="flex flex-col">
                          <span className="font-semibold text-violet-200">
                            {g.name}
                          </span>
                          <span className="text-gray-400">
                            {g.signalKeys?.length || 0} signals ×{" "}
                            {g.intervals?.length || 0} intervals ×{" "}
                            {g.rows?.length || 0} rows ={" "}
                            <span className="text-gray-200 font-semibold">
                              {total}
                            </span>{" "}
                            rules
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-gray-400">Color:</span>
                          <input
                            type="color"
                            value={groupColor || "#f97316"}
                            onChange={(e) => {
                              const c = e.target.value;
                              setAlertRuleGroups((prev) =>
                                prev.map((x) => (x.id === g.id ? { ...x, color: c } : x))
                              );
                            }}
                            className="w-7 h-6 rounded border border-gray-600 cursor-pointer bg-[#111]"
                            title="Group blink color"
                          />
                          <button
                            type="button"
                            title={hasRuleColorOverrides ? "Reset all rules in this group to use group color" : "No overrides to reset"}
                            disabled={!hasRuleColorOverrides}
                            onClick={() => {
                              setAlertRules((prev) =>
                                prev.map((r) =>
                                  r.groupId === g.id ? { ...r, color: undefined } : r
                                )
                              );
                            }}
                            className="px-2 py-0.5 rounded bg-amber-700 hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-[11px]"
                          >
                            Reset color
                          </button>
                          <button
                            type="button"
                            className="px-2 py-0.5 rounded bg-emerald-700 hover:bg-emerald-600 text-white"
                            onClick={() => {
                              setEditingGroupId(g.id);
                              setBulkGroupName(g.name || "");
                              setBulkGroupColor(g.color || "");
                              setBulkType(g.type || "number");
                              setBulkSignalKeys(g.signalKeys || []);
                              setBulkIntervals(g.intervals || []);
                              setBulkRows(g.rows || []);
                              setBulkBoolValue(
                                g.boolValue === undefined ? true : !!g.boolValue
                              );
                              setBulkStringOperator(g.stringOperator || "eq");
                              setBulkStringValue(g.stringValue || "");
                              setBulkEnumValue(g.enumValue || "BUY");
                              setBulkNumberOperator(g.numberOperator || ">=");
                              setBulkNumberThreshold(
                                g.numberThreshold === undefined ? 0 : g.numberThreshold
                              );
                            }}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="px-2 py-0.5 rounded bg-red-700 hover:bg-red-600 text-white"
                            onClick={() => {
                              if (
                                window.confirm(
                                  `Delete group "${g.name}" and all its rules?`
                                )
                              ) {
                                setAlertRuleGroups((prev) =>
                                  prev.filter((x) => x.id !== g.id)
                                );
                                setAlertRules((prev) =>
                                  prev.filter((r) => r.groupId !== g.id)
                                );
                                if (editingGroupId === g.id) {
                                  setEditingGroupId(null);
                                }
                              }
                            }}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Individual rules editor */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="font-semibold text-gray-200">
                  Rules ({alertRules.length})
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-gray-400">Sort by:</span>
                  <button
                    type="button"
                    className={`px-1.5 py-0.5 rounded ${
                      ruleSortKey === "signalKey" ? "bg-violet-700 text-white" : "bg-[#222] text-gray-300"
                    }`}
                    onClick={() => setRuleSortKey("signalKey")}
                  >
                    Signal
                  </button>
                  <button
                    type="button"
                    className={`px-1.5 py-0.5 rounded ${
                      ruleSortKey === "interval" ? "bg-violet-700 text-white" : "bg-[#222] text-gray-300"
                    }`}
                    onClick={() => setRuleSortKey("interval")}
                  >
                    Interval
                  </button>
                  <button
                    type="button"
                    className={`px-1.5 py-0.5 rounded ${
                      ruleSortKey === "rowLabel" ? "bg-violet-700 text-white" : "bg-[#222] text-gray-300"
                    }`}
                    onClick={() => setRuleSortKey("rowLabel")}
                  >
                    Candle row
                  </button>
                  <button
                    type="button"
                    className="ml-3 px-2 py-0.5 rounded bg-red-700 hover:bg-red-600 text-white"
                    onClick={() => {
                      if (alertRules.length && window.confirm("Remove all alert rules?")) {
                        setAlertRules([]);
                      }
                    }}
                  >
                    Remove all
                  </button>
                </div>
              </div>
              {(!alertRules || alertRules.length === 0) && (
                <div className="text-xs text-gray-400 mb-2">
                  No alert rules yet. Use bulk create or Add rule to create some.
                </div>
              )}
              {sortedAlertRules.map((rule, idx) => (
                <div
                  key={rule.id || idx}
                  className="grid grid-cols-1 sm:grid-cols-8 gap-2 items-center bg-[#181818] border border-gray-700 rounded-xl p-2 sm:p-3"
                >
                  <div className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-gray-400">Signal</span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                      value={rule.signalKey || SIGNAL_ROWS[0]?.key || ""}
                      onChange={(e) =>
                        setAlertRules((prev) =>
                          prev.map((r, i) =>
                            r.id === rule.id ? { ...r, signalKey: e.target.value } : r
                          )
                        )
                      }
                    >
                      {SIGNAL_ROWS.map((r) => (
                        <option key={r.key} value={r.key}>
                          {r.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-gray-400">Interval</span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                      value={rule.interval || INTERVALS[0]}
                      onChange={(e) =>
                        setAlertRules((prev) =>
                          prev.map((r, i) =>
                            r.id === rule.id ? { ...r, interval: e.target.value } : r
                          )
                        )
                      }
                    >
                      {INTERVALS.map((iv) => (
                        <option key={iv} value={iv}>
                          {iv}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-gray-400">Candle row</span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                      value={rule.rowLabel || ROW_LABELS[0]}
                      onChange={(e) =>
                        setAlertRules((prev) =>
                          prev.map((r, i) =>
                            r.id === rule.id ? { ...r, rowLabel: e.target.value } : r
                          )
                        )
                      }
                    >
                      {ROW_LABELS.map((lbl) => (
                        <option key={lbl} value={lbl}>
                          {lbl}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-gray-400">Type</span>
                    <select
                      className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                      value={rule.type || "number"}
                      onChange={(e) =>
                        setAlertRules((prev) =>
                          prev.map((r, i) =>
                            r.id === rule.id ? { ...r, type: e.target.value } : r
                          )
                        )
                      }
                    >
                      <option value="number">Number</option>
                      <option value="boolean">True / False</option>
                      <option value="string">Text (any)</option>
                      <option value="buy_sell">Buy / Sell / None</option>
                      <option value="inc_dec">Increasing / Decreasing / None</option>
                      <option value="bull_bear">Bull / Bear / None</option>
                      <option value="red_green">Red / Green / None</option>
                      <option value="trend_3">Bull_trending / Flat / Bear_trending</option>
                    </select>
                  </div>
                  {rule.type === "boolean" ? (
                    <>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Value
                        </span>
                        <select
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={String(rule.boolValue ?? true)}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r, i) =>
                                r.id === rule.id ? { ...r, boolValue: e.target.value === "true" } : r
                              )
                            )
                          }
                        >
                          <option value="true">true</option>
                          <option value="false">false</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          &nbsp;
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setAlertRules((prev) => prev.filter((r) => r.id !== rule.id))
                          }
                          className="mt-1 px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-xs"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  ) : rule.type === "string" ? (
                    <>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Condition
                        </span>
                        <select
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={rule.operator || "eq"}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r) =>
                                r.id === rule.id ? { ...r, operator: e.target.value } : r
                              )
                            )
                          }
                        >
                          <option value="eq">= equals</option>
                          <option value="neq">≠ not equal</option>
                          <option value="contains">contains</option>
                          <option value="not_contains">not contains</option>
                          <option value="starts_with">starts with</option>
                          <option value="ends_with">ends with</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Text
                        </span>
                        <input
                          type="text"
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={rule.stringValue ?? ""}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r, i) =>
                                r.id === rule.id ? { ...r, stringValue: e.target.value } : r
                              )
                            )
                          }
                        />
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          &nbsp;
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setAlertRules((prev) => prev.filter((r) => r.id !== rule.id))
                          }
                          className="mt-1 px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-xs"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  ) : rule.type === "buy_sell" ? (
                    <>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Value
                        </span>
                        <select
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={rule.enumValue ?? "BUY"}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r, i) =>
                                r.id === rule.id ? { ...r, enumValue: e.target.value } : r
                              )
                            )
                          }
                        >
                          <option value="BUY">BUY</option>
                          <option value="SELL">SELL</option>
                          <option value="NONE">NONE</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          &nbsp;
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setAlertRules((prev) => prev.filter((r) => r.id !== rule.id))
                          }
                          className="mt-1 px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-xs"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  ) : rule.type === "inc_dec" ? (
                    <>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Value
                        </span>
                        <select
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={rule.enumValue ?? "INCREASING"}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r, i) =>
                                r.id === rule.id ? { ...r, enumValue: e.target.value } : r
                              )
                            )
                          }
                        >
                          <option value="INCREASING">INCREASING</option>
                          <option value="DECREASING">DECREASING</option>
                          <option value="NONE">NONE</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          &nbsp;
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setAlertRules((prev) => prev.filter((r) => r.id !== rule.id))
                          }
                          className="mt-1 px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-xs"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  ) : rule.type === "bull_bear" ? (
                    <>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Value
                        </span>
                        <select
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={rule.enumValue ?? "BULL"}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r, i) =>
                                r.id === rule.id ? { ...r, enumValue: e.target.value } : r
                              )
                            )
                          }
                        >
                          <option value="BULL">BULL</option>
                          <option value="BEAR">BEAR</option>
                          <option value="NONE">NONE</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          &nbsp;
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setAlertRules((prev) => prev.filter((r) => r.id !== rule.id))
                          }
                          className="mt-1 px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-xs"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  ) : rule.type === "red_green" ? (
                    <>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Value
                        </span>
                        <select
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={rule.enumValue ?? "GREEN"}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r, i) =>
                                r.id === rule.id ? { ...r, enumValue: e.target.value } : r
                              )
                            )
                          }
                        >
                          <option value="GREEN">GREEN</option>
                          <option value="RED">RED</option>
                          <option value="NONE">NONE</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          &nbsp;
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setAlertRules((prev) => prev.filter((r) => r.id !== rule.id))
                          }
                          className="mt-1 px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-xs"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  ) : rule.type === "trend_3" ? (
                    <>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Value
                        </span>
                        <select
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={rule.enumValue ?? "bull_trending"}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r, i) =>
                                r.id === rule.id ? { ...r, enumValue: e.target.value } : r
                              )
                            )
                          }
                        >
                          <option value="bull_trending">bull_trending</option>
                          <option value="flat">flat</option>
                          <option value="bear_trending">bear_trending</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          &nbsp;
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setAlertRules((prev) => prev.filter((r) => r.id !== rule.id))
                          }
                          className="mt-1 px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-xs"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Condition
                        </span>
                        <select
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={rule.operator || ">="}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r) =>
                                r.id === rule.id ? { ...r, operator: e.target.value } : r
                              )
                            )
                          }
                        >
                          <option value=">">&gt;</option>
                          <option value=">=">&gt;=</option>
                          <option value="<">&lt;</option>
                          <option value="<=">&lt;=</option>
                          <option value="==">=</option>
                          <option value="!=">≠</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          Number
                        </span>
                        <input
                          type="number"
                          className="bg-[#111] border border-gray-700 rounded px-2 py-1 text-xs sm:text-sm"
                          value={rule.threshold ?? ""}
                          onChange={(e) =>
                            setAlertRules((prev) =>
                              prev.map((r, i) =>
                                r.id === rule.id ? { ...r, threshold: e.target.value } : r
                              )
                            )
                          }
                        />
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] uppercase tracking-wide text-gray-400">
                          &nbsp;
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setAlertRules((prev) => prev.filter((r) => r.id !== rule.id))
                          }
                          className="mt-1 px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-xs"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  )}
                  <div className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-gray-400">Color</span>
                    <div className="flex items-center gap-1">
                      <input
                        type="color"
                        value={(rule.color && /^#[0-9A-Fa-f]{6}$/.test(rule.color) ? rule.color : null) || (alertRuleGroups?.find((g) => g.id === rule.groupId)?.color) || masterBlinkColor || "#f97316"}
                        onChange={(e) =>
                          setAlertRules((prev) =>
                            prev.map((r, i) =>
                              r.id === rule.id ? { ...r, color: e.target.value } : r
                            )
                          )
                        }
                        className="w-7 h-6 rounded border border-gray-600 cursor-pointer bg-[#111]"
                        title="Rule blink color (overrides group/master)"
                      />
                      {(rule.color && /^#[0-9A-Fa-f]{6}$/.test(rule.color)) && (
                        <button
                          type="button"
                          onClick={() =>
                            setAlertRules((prev) =>
                              prev.map((r) => (r.id === rule.id ? { ...r, color: undefined } : r))
                            )
                          }
                          className="text-[10px] text-gray-400 hover:text-white"
                          title="Use group/master color"
                        >
                          Reset
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    const first = SIGNAL_ROWS[0];
                    setAlertRules((prev) => [
                      ...prev,
                      {
                        id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
                        signalKey: first?.key || "",
                        interval: INTERVALS[0],
                        rowLabel: ROW_LABELS[0],
                        type: "number",
                        operator: ">=",
                        threshold: 0,
                      },
                    ]);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-sm font-medium"
                >
                  Add rule
                </button>
                <button
                  type="button"
                  onClick={handleExportAlertRules}
                  className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-sm font-medium"
                >
                  Export script
                </button>
                <button
                  type="button"
                  onClick={handleImportAlertRulesClick}
                  className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-sm font-medium"
                >
                  Import script
                </button>
                <input
                  ref={importInputRef}
                  type="file"
                  accept=".json,.txt,application/json,text/plain"
                  className="hidden"
                  onChange={handleImportAlertRulesFile}
                />
              </div>
              <div className="text-[11px] text-gray-400">
                Rules are stored in your browser (localStorage). Export script to share, Import script to load.
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-6 relative">
        {!chartReady && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#111]/80 z-10 rounded-lg">
            <span className="text-white/90 text-sm">Loading chart…</span>
          </div>
        )}
        {chartReady && source === "tradingview" && typeof window !== "undefined" && !window.TradingView && (
          <div className="flex items-center justify-center py-8 text-amber-400 text-sm">
            Chart script could not load. Check network or disable ad blocker and refresh.
          </div>
        )}
        {intervalsToShow.filter(Boolean).map((intv) => (
          <div
            key={intv}
            className="grid gap-4"
            style={{ gridTemplateColumns: `repeat(${layout}, minmax(0, 1fr))` }}
          >
            {symbols.map((symbol) => {
              const safeIntv = (intv && String(intv).replace(/[^a-z0-9]/gi, "_")) || "15m";
              return (
                <div
                  key={`${symbol}-${intv}`}
                  className="bg-[#181818] rounded p-2 flex flex-col items-center"
                >
                  <div className="font-bold mb-1 text-white">
                    {symbol} — {intv}
                  </div>
                  <div
                    id={`single_tv_${symbol}_${safeIntv}`}
                    style={{ width: "100%", height: chartSize.height }}
                  />
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SingleTradeLiveView({ formattedRow: initialFormattedRow, rawTrade: initialRawTrade }) {
  const navigate = useNavigate();
  const [formattedRow, setFormattedRow] = useState(initialFormattedRow || {});
  const [rawTrade, setRawTrade] = useState(initialRawTrade ?? null);
  // When rawTrade exists, use formatTradeData to show ALL fields from the trade (same as TableView)
  const row = useMemo(
    () => (rawTrade ? formatTradeData(rawTrade, 0) : formattedRow || {}),
    [rawTrade, formattedRow]
  );
  const allKeys = Object.keys(row).filter((k) => k !== "📋" && row[k] != null && String(row[k]).trim() !== "");

  const uniqueId = rawTrade?.unique_id != null ? String(rawTrade.unique_id) : (row.Unique_ID != null ? String(stripHtml(row.Unique_ID)).trim() : null);

  useEffect(() => {
    if (!uniqueId) return;
    const intervalSec = (() => {
      try {
        const v = localStorage.getItem(REFRESH_INTERVAL_KEY);
        if (v != null) {
          const n = parseInt(v, 10);
          if (!Number.isNaN(n) && n > 0) return n;
        }
      } catch {}
      return 60;
    })();
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await apiFetch(`/api/trade?unique_id=${encodeURIComponent(uniqueId)}`);
        if (cancelled || !res.ok) return;
        const json = await res.json();
        const trade = json?.trade ?? null;
        if (cancelled || !trade) return;
        setRawTrade(trade);
        setFormattedRow(formatTradeData(trade, 0));
      } catch {
        // ignore
      }
    };
    poll();
    const id = setInterval(poll, intervalSec * 1000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [uniqueId]);

  // Call Python CalculateSignals(symbol, interval, candle) every 5 minutes for current trade pair
  const tradePair = rawTrade?.pair || stripHtml(row.Pair) || getSymbolFromUniqueId(uniqueId) || "";
  const signalSymbol = (tradePair && getRobustSymbol(tradePair)) || getSymbolFromUniqueId(uniqueId) || "BTCUSDT";
  const [signalsData, setSignalsData] = useState(null);
  const SIGNAL_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes
  useEffect(() => {
    if (!signalSymbol) return;
    const callCalculateSignals = async () => {
      try {
        const res = await apiFetch(api("/api/calculate-signals"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol: signalSymbol, candle: "regular" }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          console.warn("[CalculateSignals]", data?.message || res.statusText);
          return;
        }
        if (data?.ok && data?.intervals) setSignalsData(data);
      } catch (e) {
        console.warn("[CalculateSignals]", e?.message || e);
      }
    };
    callCalculateSignals(); // run once on mount / when pair changes
    const id = setInterval(callCalculateSignals, SIGNAL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [signalSymbol]);

  const isExistInExchange = rawTrade && (
    rawTrade.exist_in_exchange === true ||
    rawTrade.exist_in_exchange === "true" ||
    rawTrade.exist_in_exchange === 1 ||
    (typeof rawTrade.exist_in_exchange === "string" && parseFloat(rawTrade.exist_in_exchange) > 0)
  );
  const [exchangePositionData, setExchangePositionData] = useState(null);
  const [binanceDataRefreshKey, setBinanceDataRefreshKey] = useState(0);

  // --- Binance Data table settings: column order + visibility (+ actions column) ---
  const [binanceColumns, setBinanceColumns] = useState(() => {
    try {
      const v = localStorage.getItem(BINANCE_COLUMNS_ORDER_KEY);
      if (v) {
        const arr = JSON.parse(v);
        if (Array.isArray(arr) && arr.length) return arr;
      }
    } catch {}
    return [];
  });
  const [binanceColumnVisibility, setBinanceColumnVisibility] = useState(() => {
    try {
      const v = localStorage.getItem(BINANCE_COLUMNS_VISIBILITY_KEY);
      if (v) {
        const obj = JSON.parse(v);
        if (obj && typeof obj === "object") return obj;
      }
    } catch {}
    return {};
  });
  const [binanceSettingsOpen, setBinanceSettingsOpen] = useState(false);

  useEffect(() => {
    if (exchangePositionData?.positions?.length) {
      const keys = Object.keys(exchangePositionData.positions[0]);
      setBinanceColumns((prev) => {
        if (Array.isArray(prev) && prev.length > 0) {
          const ordered = prev.filter((c) => c === "__actions__" || keys.includes(c));
          const added = keys.filter((k) => !ordered.includes(k));
          return ["__actions__", ...ordered.filter((x) => x !== "__actions__"), ...added];
        }
        return ["__actions__", ...keys];
      });
      setBinanceColumnVisibility((prev) => {
        const next = { ...prev };
        ["__actions__", ...keys].forEach((k) => {
          if (next[k] === undefined) next[k] = true;
        });
        return next;
      });
    }
  }, [exchangePositionData]);

  const EXCHANGE_POLL_MS = 60 * 1000; // 1 min
  useEffect(() => {
    if (!isExistInExchange || !signalSymbol) {
      setExchangePositionData(null);
      return;
    }
    const fetchOpenPosition = async () => {
      try {
        const res = await apiFetch(api(`/api/open-position?symbol=${encodeURIComponent(signalSymbol)}`));
        const data = await res.json().catch(() => ({}));
        if (data?.ok) setExchangePositionData(data);
        else setExchangePositionData({ ok: false, error: data?.message || "Failed to fetch" });
      } catch (e) {
        setExchangePositionData({ ok: false, error: e?.message || "Network error" });
      }
    };
    fetchOpenPosition();
    const id = setInterval(fetchOpenPosition, EXCHANGE_POLL_MS);
    return () => clearInterval(id);
  }, [isExistInExchange, signalSymbol, binanceDataRefreshKey]);

  const [fieldOrder, setFieldOrder] = useState(() => {
    try {
      const v = localStorage.getItem(INFO_FIELD_ORDER_KEY);
      if (v) {
        const arr = JSON.parse(v);
        if (Array.isArray(arr) && arr.length) return arr;
      }
    } catch {}
    return null;
  });
  const [visibleKeys, setVisibleKeys] = useState(() => {
    try {
      const v = localStorage.getItem(INFO_FIELDS_KEY);
      if (v) {
        const arr = JSON.parse(v);
        if (Array.isArray(arr)) return new Set(arr);
      }
    } catch {}
    return null;
  });
  const orderedKeys = fieldOrder && fieldOrder.length
    ? [...fieldOrder.filter((k) => allKeys.includes(k)), ...allKeys.filter((k) => !fieldOrder.includes(k))]
    : allKeys;
  const keysToShow = orderedKeys.filter((k) => !visibleKeys || visibleKeys.has(k));

  // Auto-include new keys in visibleKeys so newly added trade fields show up (e.g. from SELECT * FROM alltraderecords)
  useEffect(() => {
    if (!visibleKeys || !allKeys.length) return;
    const missing = allKeys.filter((k) => !visibleKeys.has(k));
    if (missing.length > 0) {
      setVisibleKeys((prev) => new Set([...prev, ...missing]));
    }
  }, [allKeys.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const [showInfoSettings, setShowInfoSettings] = useState(false);
  const [showLayoutSettings, setShowLayoutSettings] = useState(false);
  const [showAlertSettings, setShowAlertSettings] = useState(false);
  const [sectionOrder, setSectionOrder] = useState(() => {
    try {
      const v = localStorage.getItem(SECTION_ORDER_KEY);
      if (v) {
        const arr = JSON.parse(v);
        if (Array.isArray(arr) && arr.length === SECTION_IDS.length && SECTION_IDS.every((id) => arr.includes(id))) return arr;
      }
    } catch {}
    return [...SECTION_IDS];
  });
  const [stopPrice, setStopPrice] = useState("");
  const [actionModal, setActionModal] = useState({ open: false, type: null });
  const [closeTradePreview, setCloseTradePreview] = useState(null);
  const [stopPricePreview, setStopPricePreview] = useState(null);
  const [addInvestmentPreview, setAddInvestmentPreview] = useState(null);
  const [addInvNewQty, setAddInvNewQty] = useState(null);
  const [executePreview, setExecutePreview] = useState(null);
  const [hedgePreview, setHedgePreview] = useState(null);
  const [hedgeSubmitting, setHedgeSubmitting] = useState(false);
  const endTradeRowRef = useRef(null);
  const setStopPriceRowRef = useRef(null);
  const addInvestmentRowRef = useRef(null);
  const executeRowRef = useRef(null);
  const hedgeRowRef = useRef(null);
  const clearOrderSymbolRef = useRef(null);

  const [infoGridHeight, setInfoGridHeight] = useSectionSize(INFO_GRID_HEIGHT_KEY, SIZE_CONFIG.infoGrid);
  const [infoLeftHeight, setInfoLeftHeight] = useSectionSize(INFO_LEFT_HEIGHT_KEY, SIZE_CONFIG.infoLeft);
  const [backDataHeight, setBackDataHeight] = useSectionSize(BACK_DATA_HEIGHT_KEY, SIZE_CONFIG.backData);
  const [backLeftHeight, setBackLeftHeight] = useSectionSize(BACK_LEFT_HEIGHT_KEY, SIZE_CONFIG.backLeft);
  const [chartHeight, setChartHeight] = useSectionSize(CHART_HEIGHT_KEY, SIZE_CONFIG.chart);

  const [infoSplitPercent, setInfoSplitPercent] = useState(() => {
    try {
      const v = localStorage.getItem(INFO_SPLIT_KEY);
      if (v != null) {
        const n = parseInt(v, 10);
        if (!Number.isNaN(n)) return Math.max(20, Math.min(80, n));
      }
    } catch {}
    return 50;
  });
  const [signalsTableViewMode, setSignalsTableViewMode] = useState(() => {
    try {
      const v = localStorage.getItem(SIGNALS_VIEW_MODE_KEY);
      if (v === "rowWise" || v === "intervalWise") return v;
    } catch {}
    return "intervalWise";
  });

  // Persist UI settings to localStorage only
  const saveUiSetting = useCallback((key, value) => {
    try {
      localStorage.setItem(key, typeof value === "string" ? value : JSON.stringify(value));
    } catch (_) {}
  }, []);

  useEffect(() => {
    saveUiSetting(INFO_SPLIT_KEY, infoSplitPercent);
  }, [infoSplitPercent, saveUiSetting]);
  useEffect(() => {
    saveUiSetting(SIGNALS_VIEW_MODE_KEY, signalsTableViewMode);
  }, [signalsTableViewMode, saveUiSetting]);

  // backSplitPercent is no longer used (Binance Data is a single panel now), so we stop updating it.

  const [zoomInfoLeft, zoomOutInfoLeft, zoomInInfoLeft] = useZoomLevel(ZOOM_KEYS.infoLeft);
  const [zoomInfoGrid, zoomOutInfoGrid, zoomInInfoGrid] = useZoomLevel(ZOOM_KEYS.infoGrid);
  const [zoomBackLeft, zoomOutBackLeft, zoomInBackLeft] = useZoomLevel(ZOOM_KEYS.backLeft);
  const [zoomBinanceButtons, zoomOutBinanceButtons, zoomInBinanceButtons] = useZoomLevel(ZOOM_KEYS.backButtons);
  const [zoomChart, zoomOutChart, zoomInChart] = useZoomLevel(ZOOM_KEYS.chart);

  // Binance table: text zoom vs button zoom (separate adjusters)
  const hasBinancePositions = !!exchangePositionData?.positions?.length;
  const binanceDefaultColumns = hasBinancePositions
    ? ["__actions__", ...Object.keys(exchangePositionData.positions[0])]
    : [];
  const binanceEffectiveColumns = (binanceColumns.length ? binanceColumns : binanceDefaultColumns);
  const binanceVisibleKeys = binanceEffectiveColumns.filter(
    (key) => binanceColumnVisibility[key] !== false
  );
  const binanceVisibleLabels = binanceVisibleKeys.map((key) =>
    key === "__actions__" ? "Actions" : key.replace(/([A-Z])/g, " $1").trim()
  );
  const binanceFontSizePx = (zoomBackLeft / 100) * 14;
  const binanceButtonFontSizePx = Math.max(8, Math.round((zoomBinanceButtons / 100) * 10));
  const [alertRules, setAlertRules] = useState(() => {
    try {
      const raw = localStorage.getItem(SIGNAL_ALERT_RULES_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {}
    return [];
  });
  const [alertRuleGroups, setAlertRuleGroups] = useState(() => {
    try {
      const raw = localStorage.getItem(ALERT_RULE_GROUPS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {}
    return [];
  });
  const [masterBlinkColor, setMasterBlinkColor] = useState(() => {
    try {
      const v = localStorage.getItem(MASTER_BLINK_COLOR_KEY);
      return v && /^#[0-9A-Fa-f]{6}$/.test(v) ? v : "#f97316";
    } catch {}
    return "#f97316";
  });
  const importInputRef = useRef(null);

  // Fetch quantity for add-investment preview when new amount changes
  useEffect(() => {
    if (!addInvestmentPreview?.symbol || !addInvestmentPreview?.newAmount) {
      setAddInvNewQty(null);
      return;
    }
    const num = parseFloat(addInvestmentPreview.newAmount);
    if (Number.isNaN(num) || num <= 0) {
      setAddInvNewQty(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const url = api(`/api/quantity-preview?symbol=${encodeURIComponent(addInvestmentPreview.symbol)}&invest=${encodeURIComponent(num)}`);
        const res = await apiFetch(url);
        const data = await res.json().catch(() => ({}));
        if (data?.ok && data.quantity != null) setAddInvNewQty(data.quantity);
        else setAddInvNewQty(null);
      } catch {
        setAddInvNewQty(null);
      }
    }, 400);
    return () => clearTimeout(t);
  }, [addInvestmentPreview?.symbol, addInvestmentPreview?.newAmount]);

  useEffect(() => {
    if (fieldOrder && fieldOrder.length) {
      try {
        localStorage.setItem(INFO_FIELD_ORDER_KEY, JSON.stringify(fieldOrder));
      } catch {}
      saveUiSetting(INFO_FIELD_ORDER_KEY, fieldOrder);
    }
  }, [fieldOrder, saveUiSetting]);
  useEffect(() => {
    if (visibleKeys && visibleKeys.size > 0) {
      try {
        localStorage.setItem(INFO_FIELDS_KEY, JSON.stringify([...visibleKeys]));
      } catch {}
      saveUiSetting(INFO_FIELDS_KEY, [...visibleKeys]);
    }
  }, [visibleKeys, saveUiSetting]);
  useEffect(() => {
    try {
      localStorage.setItem(SECTION_ORDER_KEY, JSON.stringify(sectionOrder));
    } catch {}
    saveUiSetting(SECTION_ORDER_KEY, sectionOrder);
  }, [sectionOrder, saveUiSetting]);
  useEffect(() => {
    if (binanceColumns.length > 0) {
      try {
        localStorage.setItem(BINANCE_COLUMNS_ORDER_KEY, JSON.stringify(binanceColumns));
      } catch {}
      saveUiSetting(BINANCE_COLUMNS_ORDER_KEY, binanceColumns);
    }
  }, [binanceColumns, saveUiSetting]);
  useEffect(() => {
    if (Object.keys(binanceColumnVisibility).length > 0) {
      try {
        localStorage.setItem(BINANCE_COLUMNS_VISIBILITY_KEY, JSON.stringify(binanceColumnVisibility));
      } catch {}
      saveUiSetting(BINANCE_COLUMNS_VISIBILITY_KEY, binanceColumnVisibility);
    }
  }, [binanceColumnVisibility, saveUiSetting]);
  useEffect(() => {
    try {
      localStorage.setItem(SIGNAL_ALERT_RULES_KEY, JSON.stringify(alertRules));
    } catch {}
  }, [alertRules]);
  useEffect(() => {
    try {
      localStorage.setItem(ALERT_RULE_GROUPS_KEY, JSON.stringify(alertRuleGroups));
    } catch {}
  }, [alertRuleGroups]);
  useEffect(() => {
    try {
      if (masterBlinkColor && /^#[0-9A-Fa-f]{6}$/.test(masterBlinkColor)) {
        localStorage.setItem(MASTER_BLINK_COLOR_KEY, masterBlinkColor);
      }
    } catch {}
  }, [masterBlinkColor]);

  const handleExportAlertRules = useCallback(() => {
    if (typeof window === "undefined" || !window.document) return;
    try {
      const payload = {
        type: "lab_single_trade_alert_rules",
        version: 2,
        createdAt: new Date().toISOString(),
        masterBlinkColor: masterBlinkColor || "#f97316",
        rules: alertRules || [],
        groups: alertRuleGroups || [],
      };
      const json = JSON.stringify(payload, null, 2);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ts = new Date().toISOString().replace(/[:.]/g, "-");
      a.download = `lab-alert-rules-${ts}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("[AlertRules] Export failed:", e);
      if (typeof window !== "undefined") {
        window.alert("Failed to export rules. See console for details.");
      }
    }
  }, [alertRules, alertRuleGroups, masterBlinkColor]);

  const handleImportAlertRulesClick = useCallback(() => {
    if (importInputRef.current) {
      importInputRef.current.value = "";
      importInputRef.current.click();
    }
  }, []);

  const handleImportAlertRulesFile = useCallback((event) => {
    try {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const text = String(e.target?.result || "");
          const parsed = JSON.parse(text);
          const rules = Array.isArray(parsed)
            ? parsed
            : Array.isArray(parsed?.rules)
              ? parsed.rules
              : null;
          if (!rules) {
            window.alert("Invalid script file: expected an array of rules.");
            return;
          }
          let groups = Array.isArray(parsed?.groups) ? parsed.groups : [];
          let rulesToSet = rules;
          if (groups.length === 0) {
            const defaultGroupId = "imported-" + Date.now();
            const defaultGroup = {
              id: defaultGroupId,
              name: "Imported",
              color: parsed?.masterBlinkColor && /^#[0-9A-Fa-f]{6}$/.test(parsed.masterBlinkColor) ? parsed.masterBlinkColor : "#f97316",
            };
            groups = [defaultGroup];
            rulesToSet = rules.map((r) => ({ ...r, groupId: defaultGroupId }));
          } else {
            const groupIds = new Set(groups.map((g) => g.id));
            rulesToSet = rules.map((r) => {
              if (r.groupId && groupIds.has(r.groupId)) return r;
              const firstGroupId = groups[0]?.id;
              return { ...r, groupId: firstGroupId || r.groupId };
            });
          }
          setAlertRules(rulesToSet);
          setAlertRuleGroups(groups);
          if (parsed?.masterBlinkColor && /^#[0-9A-Fa-f]{6}$/.test(parsed.masterBlinkColor)) {
            setMasterBlinkColor(parsed.masterBlinkColor);
          }
        } catch (err) {
          console.error("[AlertRules] Import parse error:", err);
          window.alert("Failed to parse script file. See console for details.");
        }
      };
      reader.readAsText(file);
    } catch (err) {
      console.error("[AlertRules] Import failed:", err);
      if (typeof window !== "undefined") {
        window.alert("Failed to import rules. See console for details.");
      }
    }
  }, []);

  const chartSize = { width: 500, height: chartHeight };

  // All API calls go to server.js (Node); Node proxies to Python where needed. Never call Python from frontend.
  const handleExecute = useCallback(async ({ password }) => {
    const rowData = executeRowRef.current;
    const symbol = (rowData?.symbol || signalSymbol || (rawTrade?.pair || stripHtml(row.Pair) || "").replace("/", "").trim()).toString().toUpperCase();
    const amount = (rowData?.amount ?? "").toString().trim();
    const stop_price = (rowData?.stop_price ?? "").toString().trim();
    if (!symbol) throw new Error("Symbol not found");
    if (!amount) throw new Error("Investment amount required");
    if (!stop_price) throw new Error("Stop price required");
    const url = api("/api/execute");
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, amount, stop_price, position_side: "LONG", password: (password || "").trim() }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.message || data?.error || "Execute failed");
    if (data?.ok === false) throw new Error(data?.message || "Execute failed");
    executeRowRef.current = null;
    setBinanceDataRefreshKey((k) => k + 1);
    return { successMessage: data?.message || "Order placed." };
  }, [signalSymbol, rawTrade?.pair, row.Pair]);
  // Flow: Frontend → server.js (Node) → Python. POST to Node /api/end-trade; Node verifies password and proxies to Python.
  const handleEndTrade = useCallback(async ({ password }) => {
    const rowData = endTradeRowRef.current;
    const sym = (rowData?.symbol || signalSymbol || (rawTrade?.pair || stripHtml(row.Pair) || "").replace("/", "").trim()).toString().toUpperCase();
    if (!sym) throw new Error("Symbol not found for this trade");
    const position_side = (rowData?.positionSide || "BOTH").toString().trim().toUpperCase();
    const amt = rowData?.positionAmt != null ? parseFloat(rowData.positionAmt) : NaN;
    const quantity = !Number.isNaN(amt) && amt !== 0 ? Math.abs(amt) : undefined;
    const url = api("/api/end-trade");
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        unique_id: rawTrade?.unique_id,
        symbol: sym,
        position_side: ["LONG", "SHORT", "BOTH"].includes(position_side) ? position_side : "BOTH",
        quantity: quantity != null && quantity > 0 ? quantity : undefined,
        password: (password || "").trim(),
      }),
    });
    const data = await res.json().catch(() => ({ message: res.statusText }));
    if (!res.ok) throw new Error(data?.message || data?.error || "Close trade failed");
    if (data?.ok === false) throw new Error(data?.message || "Close trade failed");
    endTradeRowRef.current = null;
    setBinanceDataRefreshKey((k) => k + 1);
    return { successMessage: data?.message || "Position closed." };
  }, [rawTrade?.unique_id, rawTrade?.pair, signalSymbol, row.Pair]);
  const handleHedge = useCallback(async ({ password }) => {
    const rowData = hedgeRowRef.current;
    const symbol = (rowData?.symbol || signalSymbol || (rawTrade?.pair || stripHtml(row.Pair) || "").replace("/", "").trim()).toString().toUpperCase();
    const position_side = (rowData?.positionSide || "LONG").toString().toUpperCase();
    const quantity = rowData?.quantity;
    if (!symbol) throw new Error("Symbol not found");
    if (quantity == null || quantity === "" || Number(parseFloat(quantity)) <= 0) throw new Error("Quantity required");
    setHedgeSubmitting(true);
    try {
      const url = api("/api/hedge");
      const res = await apiFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, position_side, quantity, password: (password || "").trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (data?.ok === false) throw new Error(data?.message || "Hedge failed");
      if (!res.ok) throw new Error(data?.message || data?.error || "Hedge failed");
      hedgeRowRef.current = null;
      setBinanceDataRefreshKey((k) => k + 1);
      return { successMessage: data?.message || "Hedge order placed." };
    } finally {
      setHedgeSubmitting(false);
    }
  }, [signalSymbol, rawTrade?.pair, row.Pair]);
  const handleSetStopPrice = useCallback(async ({ password, extraValue }) => {
    const row = setStopPriceRowRef.current;
    const symbol = (row?.symbol || signalSymbol || "").toString().trim().toUpperCase();
    const position_side = (row?.positionSide || "BOTH").toString().toUpperCase();
    const stop_price = (row?.stopPrice ?? extraValue ?? stopPrice ?? "").toString().trim();
    if (!symbol) throw new Error("Symbol not found");
    if (!stop_price) throw new Error("Stop price required");
    const url = api("/api/stop-price");
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, position_side, stop_price, password: (password || "").trim() }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.message || data?.error || "Set stop price failed");
    if (data?.ok === false) throw new Error(data?.message || "Set stop price failed");
    setStopPriceRowRef.current = null;
    setBinanceDataRefreshKey((k) => k + 1);
    return { successMessage: data?.message || "Stop price set." };
  }, [signalSymbol, stopPrice]);
  const handleAddInvestment = useCallback(async ({ password }) => {
    const row = addInvestmentRowRef.current;
    const symbol = (row?.symbol || signalSymbol || "").toString().trim().toUpperCase();
    const position_side = (row?.positionSide || "LONG").toString().toUpperCase();
    const amount = (row?.amount ?? "").toString().trim();
    if (!symbol) throw new Error("Symbol not found");
    if (!amount) throw new Error("Amount required");
    const url = api("/api/add-investment");
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, position_side, amount, password: (password || "").trim() }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.message || data?.error || "Add investment failed");
    if (data?.ok === false) throw new Error(data?.message || "Add investment failed");
    addInvestmentRowRef.current = null;
    setBinanceDataRefreshKey((k) => k + 1);
    return { successMessage: data?.message || "Investment added." };
  }, [signalSymbol]);
  // Clear Order: Frontend → server.js → Python main_binance.closeOrder(symbol). Cancels all open orders (TP/SL) for the symbol.
  const handleClear = useCallback(async ({ password }) => {
    const rowSym = clearOrderSymbolRef.current;
    const sym = (rowSym || signalSymbol || (rawTrade?.pair || stripHtml(row.Pair) || "").replace("/", "").trim()).toString().toUpperCase();
    if (!sym) throw new Error("Symbol not found");
    const url = api("/api/close-order");
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym, password: (password || "").trim() }),
    });
    const data = await res.json().catch(() => ({ message: res.statusText }));
    if (!res.ok) throw new Error(data.message || data.error || "Close order failed");
    if (data?.ok === false) throw new Error(data.message || "Close order failed");
    clearOrderSymbolRef.current = null;
    setBinanceDataRefreshKey((k) => k + 1);
    return { successMessage: data.message || "The operation of cancel all open order is done." };
  }, [signalSymbol, rawTrade?.pair, row.Pair]);

  const isAutoEnabled = rawTrade?.auto === true || rawTrade?.auto === "true" || rawTrade?.auto === 1;
  const handleAutoPilot = useCallback(async ({ password, extraValue }) => {
    const unique_id = rawTrade?.unique_id;
    const machineid = rawTrade?.machineid;
    const enabled = extraValue === "enable";
    const url = api("/api/autopilot");
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unique_id, machineid, password: (password || "").trim(), enabled }),
    });
    const data = await res.json().catch(() => ({ message: res.statusText }));
    if (!res.ok) {
      const msg = data.message || data.detail || data.error || res.statusText;
      if (res.status === 404) {
        throw new Error(data.message || "API endpoint not found. Is the server running? If using GitHub Pages, set API_BASE_URL and redeploy.");
      }
      throw new Error(msg || `API error ${res.status}`);
    }
    if (data && data.ok === false) {
      throw new Error(data.message || "Autopilot update failed");
    }
    try {
      const tradeRes = await apiFetch(`/api/trade?unique_id=${encodeURIComponent(unique_id)}`);
      if (tradeRes.ok) {
        const tradeJson = await tradeRes.json();
        const trade = tradeJson?.trade ?? null;
        if (trade) {
          setRawTrade(trade);
          setFormattedRow(formatTradeData(trade, 0));
        }
      }
    } catch (_) {}
    return data;
  }, [rawTrade?.unique_id, rawTrade?.machineid]);

  const getConfirmHandler = useCallback((type) => {
    switch (type) {
      case "execute": return handleExecute;
      case "endTrade": return handleEndTrade;
      case "autoPilot": return handleAutoPilot;
      case "hedge": return handleHedge;
      case "setStopPrice": return handleSetStopPrice;
      case "addInvestment": return handleAddInvestment;
      case "clear": return handleClear;
      default: return async () => {};
    }
  }, [handleExecute, handleEndTrade, handleAutoPilot, handleHedge, handleSetStopPrice, handleAddInvestment, handleClear]);

  return (
    <div className="fixed inset-0 flex flex-col bg-[#f5f6fa] dark:bg-[#0f0f0f] text-[#222] dark:text-white overflow-hidden w-full">
      <div className="flex-none flex items-center justify-between gap-2 px-3 sm:px-4 py-2 bg-[#181818] text-white border-b border-gray-700 shadow-md flex-wrap">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 font-medium transition-colors min-h-[40px] shrink-0"
        >
          ← Back
        </button>
        <span className="font-semibold text-base sm:text-lg truncate min-w-0">Live Trade — {stripHtml(row.Pair) || "N/A"}</span>
        <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
          <UserEmailDisplay />
          <LogoutButton className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-semibold shrink-0" />
          <button
            type="button"
            onClick={() => setShowLayoutSettings(true)}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 transition-colors min-h-[40px] shrink-0"
            title="Section order"
          >
            <LayoutGrid size={20} />
            Layout
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden p-3 sm:p-4 space-y-3 sm:space-y-4 min-h-0">
        {sectionOrder.map((id) => {
          if (id === "information") return (
        <section key="information" className="rounded-xl border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#181a20] overflow-hidden shadow-lg flex-shrink-0 flex flex-col" style={{ minHeight: 200 }}>
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 sm:px-4 py-2.5 bg-gradient-to-r from-teal-800 to-teal-700 text-white font-semibold flex-shrink-0">
            <span className="text-sm sm:text-base">Information</span>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-white/90 text-xs mr-1">Grid zoom:</span>
              <ZoomControls
                onDecrease={zoomOutInfoGrid}
                onIncrease={zoomInInfoGrid}
                current={zoomInfoGrid}
                label="Zoom grid"
                className="min-w-[32px] min-h-[32px] flex items-center justify-center rounded-lg bg-white/20 hover:bg-white/30 text-white text-xs font-bold disabled:opacity-40"
              />
              <button
                type="button"
                onClick={() => setShowInfoSettings(true)}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-sm font-medium transition-colors min-h-[36px] sm:min-h-[40px]"
              >
                <Settings size={18} />
                Settings
              </button>
              <button
                type="button"
                disabled={hasBinancePositions}
                onClick={() => {
                  const sym = (signalSymbol || (rawTrade?.pair || stripHtml(row.Pair) || "").replace("/", "").trim()).toString().toUpperCase();
                  const backInvestNum = rawTrade?.investment != null && rawTrade?.investment !== ""
                    ? parseFloat(rawTrade.investment)
                    : parseFloat(String(row.Investment || "").replace(/[$,]/g, ""));
                  const backInvest = Number.isFinite(backInvestNum) ? backInvestNum : 0;
                  const stopPriceVal = rawTrade?.stop_price != null && rawTrade?.stop_price !== ""
                    ? String(rawTrade.stop_price).trim()
                    : String(row.Stop_Price || "").replace(/,/g, "").trim();
                  setExecutePreview({
                    symbol: sym,
                    backInvest,
                    liveInvest: backInvest > 0 ? String(backInvest) : "",
                    stopPrice: stopPriceVal,
                  });
                }}
                className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-emerald-500 via-green-500 to-teal-500 hover:from-emerald-600 hover:via-green-600 hover:to-teal-600 text-white text-lg font-bold shadow-lg shadow-emerald-500/40 hover:shadow-emerald-500/50 hover:scale-105 active:scale-100 transition-all min-h-[48px] border-2 border-emerald-400/50 disabled:opacity-50 disabled:pointer-events-none disabled:hover:scale-100 disabled:cursor-not-allowed"
                title={hasBinancePositions ? "Disabled: position already exists in Binance Data" : "Execute Trade in Exchange"}
              >
                <Play size={24} fill="currentColor" />
                {hasBinancePositions ? "Disabled: position already exists in Binance Data" : "Execute Trade in Exchange"}
              </button>
            </div>
          </div>
          <div className="flex min-h-0 p-3 sm:p-4 gap-0 flex-shrink-0" style={{ height: infoGridHeight }}>
            <div
              className="border border-gray-300 dark:border-gray-600 rounded-xl flex flex-col overflow-hidden flex-shrink-0 bg-white dark:bg-[#0d0d0d]"
              style={{ width: `${infoSplitPercent}%`, minHeight: infoLeftHeight, fontSize: `${(zoomInfoLeft / 100) * 11}px` }}
            >
              <div className="flex items-center gap-2 p-1.5 border-b border-gray-200 dark:border-gray-700 flex-shrink-0 flex-wrap">
                <ZoomControls
                  onDecrease={zoomOutInfoLeft}
                  onIncrease={zoomInInfoLeft}
                  current={zoomInfoLeft}
                  label="Zoom"
                  className="min-w-[28px] min-h-[28px] flex items-center justify-center rounded bg-gray-300 hover:bg-gray-400 dark:bg-gray-600 dark:hover:bg-gray-500 disabled:opacity-40 text-gray-800 dark:text-white text-xs font-bold"
                />
                <span className="text-xs font-semibold text-gray-600 dark:text-white truncate">
                  {signalsData?.symbol || signalSymbol || "—"} signals
                </span>
                <div className="ml-auto flex items-center gap-2">
                  {signalsData?.ok && signalsData?.intervals && (
                    <button
                      type="button"
                      onClick={() => setSignalsTableViewMode((m) => (m === "intervalWise" ? "rowWise" : "intervalWise"))}
                      className="px-2 py-1 rounded text-xs font-medium bg-teal-600 hover:bg-teal-700 text-white whitespace-nowrap"
                    >
                      Change view
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setShowAlertSettings(true)}
                    className="px-2 py-1 rounded text-xs font-medium bg-violet-600 hover:bg-violet-700 text-white whitespace-nowrap"
                  >
                    Alert settings
                  </button>
                </div>
              </div>
              <div className="flex-1 min-h-0 overflow-auto">
                {signalsData?.ok && signalsData?.intervals ? (
                  (() => {
                    const isIntervalWise = signalsTableViewMode === "intervalWise";
                    const columns = isIntervalWise
                      ? INTERVALS.flatMap((iv, gIdx) =>
                          ROW_LABELS.map((label) => ({
                            iv,
                            label,
                            rowIdx: ROW_LABEL_TO_DATA_INDEX[label] ?? 0,
                            groupKey: iv,
                            groupIndex: gIdx,
                          }))
                        )
                      : ROW_LABELS.flatMap((label, gIdx) =>
                          INTERVALS.map((iv) => ({
                            iv,
                            label,
                            rowIdx: ROW_LABEL_TO_DATA_INDEX[label] ?? 0,
                            groupKey: label,
                            groupIndex: gIdx,
                          }))
                        );
                    const groupColors = isIntervalWise ? INTERVAL_GROUP_COLORS : ROW_GROUP_COLORS;
                    const getGroupColor = (groupIndex) => groupColors[groupIndex] ?? "";

                    const matchesRuleValue = (rule, v) => {
                      if (!rule) return false;

                      // Boolean flags (true/false)
                      if (rule.type === "boolean") {
                        const boolVal = v === true || v === "true" || v === 1 || v === "1";
                        const target =
                          rule.boolValue === undefined ? true : !!rule.boolValue;
                        return boolVal === target;
                      }

                      // Text / enums (buy/sell/none, bull/bear, etc.)
                      if (
                        rule.type === "string" ||
                        rule.type === "buy_sell" ||
                        rule.type === "inc_dec" ||
                        rule.type === "bull_bear" ||
                        rule.type === "red_green" ||
                        rule.type === "trend_3"
                      ) {
                        const valueStr = (v == null ? "" : String(v)).toLowerCase().trim();
                        const rawTarget =
                          rule.type === "string"
                            ? rule.stringValue
                            : rule.enumValue;
                        const targetStr = (rawTarget ?? "").toString().toLowerCase().trim();
                        const op = rule.operator || "eq";

                        switch (op) {
                          case "neq":
                            return valueStr !== targetStr;
                          case "contains":
                            return valueStr.includes(targetStr);
                          case "not_contains":
                            return !valueStr.includes(targetStr);
                          case "starts_with":
                            return valueStr.startsWith(targetStr);
                          case "ends_with":
                            return valueStr.endsWith(targetStr);
                          case "eq":
                          default:
                            return valueStr === targetStr;
                        }
                      }

                      // Numeric comparisons
                      const num = typeof v === "number" ? v : parseFloat(v);
                      if (!Number.isFinite(num)) return false;
                      const threshold = Number(rule.threshold);
                      switch (rule.operator) {
                        case ">":
                          return num > threshold;
                        case ">=":
                          return num >= threshold;
                        case "<":
                          return num < threshold;
                        case "<=":
                          return num <= threshold;
                        case "==":
                          return num === threshold;
                        case "!=":
                          return num !== threshold;
                        default:
                          return false;
                      }
                    };

                    // Count how many cells per row are currently matching alert rules,
                    // so rows with the highest alert activity can float to the top.
                    const rowAlertCounts = {};
                    SIGNAL_ROWS.forEach(({ key }) => {
                      rowAlertCounts[key] = 0;
                    });
                    if (alertRules && alertRules.length && signalsData?.intervals) {
                      SIGNAL_ROWS.forEach(({ key }) => {
                        columns.forEach((col) => {
                          const summary = signalsData.intervals[col.iv]?.summary;
                          const rows = Array.isArray(summary) ? summary : [];
                          const v = rows[col.rowIdx]?.[key];
                          const matching = alertRules.filter(
                            (rule) =>
                              rule &&
                              rule.signalKey === key &&
                              rule.interval === col.iv &&
                              rule.rowLabel === col.label
                          );
                          if (!matching.length) return;
                          const cellMatches = matching.some((rule) =>
                            matchesRuleValue(rule, v)
                          );
                          if (cellMatches) {
                            rowAlertCounts[key] = (rowAlertCounts[key] || 0) + 1;
                          }
                        });
                      });
                    }
                    const sortedSignalRows = [...SIGNAL_ROWS].sort(
                      (a, b) =>
                        (rowAlertCounts[b.key] || 0) - (rowAlertCounts[a.key] || 0)
                    );
                    return (
                      <table className="w-full border-collapse" style={{ fontSize: "1em" }}>
                        <thead className="sticky top-0 bg-gray-100 dark:bg-gray-800 z-10">
                          <tr>
                            <th className="border border-gray-300 dark:border-gray-600 px-1 py-0.5 text-left font-semibold text-gray-700 dark:text-gray-300 whitespace-nowrap min-w-[80px]">Signal</th>
                            {columns.map((col, idx) => (
                              <th
                                key={`${col.iv}-${col.label}-${idx}`}
                                className={`border border-gray-300 dark:border-gray-600 px-0.5 py-0.5 text-center font-medium text-gray-600 dark:text-white whitespace-nowrap ${getGroupColor(col.groupIndex)}`}
                              >
                                {col.iv} {col.label}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {sortedSignalRows.map(({ label, key }) => {
                            const allLabels = SIGNAL_ROWS.map((r) => r.label);
                            const displayLabel = formatSignalName(label, allLabels);
                            return (
                            <tr key={key} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                              <td className="border border-gray-200 dark:border-gray-600 px-1 py-0.5 font-medium text-teal-700 dark:text-teal-400 whitespace-nowrap truncate max-w-[100px]" title={label}>
                                {displayLabel}
                              </td>
                              {columns.map((col, idx) => {
                                const summary = signalsData.intervals[col.iv]?.summary;
                                const rows = Array.isArray(summary) ? summary : [];
                                const v = rows[col.rowIdx]?.[key];
                                const str = v != null ? (typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed?.(4) ?? String(v)) : String(v)) : "—";
                                const cellBg = getGroupColor(col.groupIndex);
                                const matchingRules = (() => {
                                  if (!alertRules || !alertRules.length) return [];
                                  return alertRules.filter((rule) =>
                                    rule &&
                                    rule.signalKey === key &&
                                    rule.interval === col.iv &&
                                    rule.rowLabel === col.label
                                  );
                                })();
                                const hasAlert = matchingRules.some((rule) => matchesRuleValue(rule, v));
                                const firstMatching = hasAlert ? matchingRules.find((rule) => matchesRuleValue(rule, v)) : null;
                                const groupForRule = firstMatching?.groupId && alertRuleGroups ? alertRuleGroups.find((g) => g.id === firstMatching.groupId) : null;
                                const effectiveColor = (firstMatching?.color && /^#[0-9A-Fa-f]{6}$/.test(firstMatching.color))
                                  ? firstMatching.color
                                  : (groupForRule?.color && /^#[0-9A-Fa-f]{6}$/.test(groupForRule.color))
                                    ? groupForRule.color
                                    : (masterBlinkColor && /^#[0-9A-Fa-f]{6}$/.test(masterBlinkColor)) ? masterBlinkColor : "#f97316";
                                const hexToRgba = (hex, a) => {
                                  const n = parseInt(hex.slice(1), 16);
                                  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
                                  return `rgba(${r},${g},${b},${a})`;
                                };
                                const alertStyle = hasAlert ? {
                                  "--lab-alert-bg": effectiveColor,
                                  "--lab-alert-bg-peak": effectiveColor,
                                  "--lab-alert-shadow": hexToRgba(effectiveColor, 0.9),
                                } : undefined;
                                const alertClasses = hasAlert ? "lab-alert-cell" : "";
                                return (
                                  <td
                                    key={`${col.iv}-${col.label}-${idx}`}
                                    className={`border border-gray-200 dark:border-gray-600 px-0.5 py-0.5 text-center text-gray-800 dark:text-white truncate max-w-[60px] ${cellBg} ${alertClasses}`}
                                    style={alertStyle}
                                    title={str}
                                  >
                                    {str}
                                  </td>
                                );
                              })}
                            </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    );
                  })()
                ) : (
                  <div className="flex items-center justify-center h-full text-gray-500 dark:text-white text-center p-2">Loading signals…</div>
                )}
              </div>
            </div>
            <WidthDragger leftPercent={infoSplitPercent} onChange={setInfoSplitPercent} min={20} max={80} />
            <div className="min-w-0 flex-1 flex flex-col overflow-hidden" style={{ width: `${100 - infoSplitPercent}%` }}>
              <div
                className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 sm:gap-3 overflow-y-auto pr-1 flex-1 min-h-0"
                style={{ fontSize: `${(zoomInfoGrid / 100) * 14}px` }}
              >
                {keysToShow.map((key) => (
                  <div
                    key={key}
                    className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gradient-to-br from-gray-50 to-white dark:from-[#1e1e1e] dark:to-[#252525] p-3 shadow-sm hover:shadow-md hover:border-teal-400/50 dark:hover:border-teal-500/50 transition-all"
                  >
                    <div className="font-semibold uppercase tracking-wide text-teal-700 dark:text-teal-400 mb-1 truncate" style={{ fontSize: "1em" }} title={key.replace(/_/g, " ")}>
                      {key.replace(/_/g, " ")}
                    </div>
                    <div className="font-medium text-[#222] dark:text-white break-words leading-snug max-h-14 overflow-hidden" style={{ fontSize: "1em" }} title={stripHtml(row[key])}>
                      {stripHtml(row[key])}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <HeightDragger
            value={infoGridHeight}
            min={SIZE_CONFIG.infoGrid.min}
            max={SIZE_CONFIG.infoGrid.max}
            onChange={setInfoGridHeight}
            label="Drag to resize Information section height"
          />
        </section>
          );
          if (id === "binanceData") return (
        <section key="binanceData" className="rounded-xl border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#181a20] overflow-hidden shadow-lg flex-shrink-0 flex flex-col relative">
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 sm:px-4 py-2.5 bg-gradient-to-r from-teal-800 to-teal-700 text-white font-semibold flex-shrink-0">
            <span className="text-sm sm:text-base">Binance Data</span>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-white/90 text-xs mr-1">Zoom:</span>
              <ZoomControls
                onDecrease={zoomOutBackLeft}
                onIncrease={zoomInBackLeft}
                current={zoomBackLeft}
                label="Zoom Binance table"
                className="min-w-[32px] min-h-[32px] flex items-center justify-center rounded-lg bg-white/20 hover:bg-white/30 text-white text-xs font-bold disabled:opacity-40"
              />
              <span className="text-white/90 text-xs mr-1 ml-1">Buttons:</span>
              <ZoomControls
                onDecrease={zoomOutBinanceButtons}
                onIncrease={zoomInBinanceButtons}
                current={zoomBinanceButtons}
                label="Binance button size"
                className="min-w-[32px] min-h-[32px] flex items-center justify-center rounded-lg bg-white/20 hover:bg-white/30 text-white text-xs font-bold disabled:opacity-40"
              />
              {exchangePositionData?.positions?.length ? (
                <button
                  type="button"
                  onClick={() => setBinanceSettingsOpen((open) => !open)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-xs font-semibold shadow-sm border border-teal-200/60"
                  title="Reorder / show or hide Binance columns"
                >
                  ⚙
                  <span>Settings</span>
                </button>
              ) : null}
            </div>
          </div>
          <div
            className="flex min-h-0 p-3 sm:p-4 flex-shrink-0"
            style={{ height: backDataHeight }}
          >
            <div
              className="w-full border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-xl flex flex-col items-center justify-center text-gray-800 dark:text-white bg-gray-50 dark:bg-[#0d0d0d] overflow-hidden flex-shrink-0"
              style={{ minHeight: backLeftHeight }}
            >
              <div className="flex flex-col gap-2 mb-2 flex-wrap justify-center p-2 overflow-auto w-full">
                {!isExistInExchange ? (
                  <span className="text-gray-500 dark:text-white text-center">Trade not in exchange — no live data</span>
                ) : exchangePositionData?.ok === false ? (
                  <span className="text-amber-600 dark:text-amber-400 text-center">{exchangePositionData?.error || "Failed to fetch"}</span>
                ) : hasBinancePositions ? (
                  <div className="relative overflow-auto w-full">
                    {binanceSettingsOpen && (
                      <BinanceColumnsModal
                        columns={binanceEffectiveColumns}
                        setColumns={setBinanceColumns}
                        visibility={binanceColumnVisibility}
                        setVisibility={setBinanceColumnVisibility}
                        onClose={() => setBinanceSettingsOpen(false)}
                      />
                    )}
                    <table className="w-full border-collapse border border-gray-300 dark:border-gray-600">
                      <thead>
                        <tr className="bg-teal-100 dark:bg-teal-900/40">
                          {binanceVisibleKeys.map((key, idx) => {
                            const baseLabel = binanceVisibleLabels[idx];
                            const headerLabel =
                              key === "__actions__"
                                ? baseLabel
                                : formatSignalName(baseLabel, binanceVisibleLabels);
                            return (
                              <th
                                key={key}
                                className="border border-gray-300 dark:border-gray-600 px-2 py-1 text-left font-medium text-teal-800 dark:text-teal-200 whitespace-nowrap max-w-[80px] truncate"
                                title={baseLabel}
                              >
                                <div
                                  className="flex flex-col leading-tight"
                                  style={{ fontSize: `${binanceFontSizePx}px` }}
                                >
                                  <span className="truncate">{headerLabel}</span>
                                  {headerLabel !== baseLabel && (
                                    <span className="text-[10px] text-teal-700/80 dark:text-teal-200/80 truncate">
                                      {baseLabel}
                                    </span>
                                  )}
                                </div>
                              </th>
                            );
                          })}
                        </tr>
                      </thead>
                      <tbody>
                        {exchangePositionData.positions.map((pos, idx) => {
                          const formatVal = (key, val) => {
                            if (val === null || val === undefined) return "\u2014";
                            const num = parseFloat(val);
                            if (!isNaN(num) && typeof val !== "boolean") {
                              if (key.toLowerCase().includes("price") || key.toLowerCase().includes("notional") || key.toLowerCase().includes("margin") || key.toLowerCase().includes("profit")) return num.toFixed(4);
                              if (Number.isInteger(num) || (key.toLowerCase().includes("amt") || key.toLowerCase().includes("qty"))) return num.toFixed(4);
                              return num.toFixed(2);
                            }
                            if (typeof val === "boolean") return val ? "\u2713" : "\u2717";
                            if (typeof val === "object") return JSON.stringify(val);
                            return String(val);
                          };
                          const keysToRender = binanceVisibleKeys;
                          return (
                            <tr key={idx} className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-[#1a1a1a] hover:bg-gray-50 dark:hover:bg-[#252525]">
                              {keysToRender.map((key) => {
                                if (key === "__actions__") {
                                  return (
                                    <td
                                      key="__actions__"
                                      className="border border-gray-200 dark:border-gray-700 px-2 py-1 whitespace-nowrap"
                                      style={{ fontSize: `${binanceButtonFontSizePx}px` }}
                                    >
                                      <div className="flex flex-wrap gap-1">
                                        <button
                                          type="button"
                                          onClick={() => setActionModal({ open: true, type: "autoPilot", autoEnable: !isAutoEnabled })}
                                          className="px-2 py-0.5 rounded bg-violet-600 hover:bg-violet-700 text-white font-semibold"
                                          title={isAutoEnabled ? "Disable Auto-Pilot" : "Enable Auto-Pilot"}
                                        >
                                          {isAutoEnabled ? "Auto Disable" : "Auto Enable"}
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => {
                                            const symbol = (pos.symbol || signalSymbol || "").toString().toUpperCase();
                                            const positionSide = pos.positionSide ?? "BOTH";
                                            const amt = pos.positionAmt != null ? parseFloat(pos.positionAmt) : NaN;
                                            const quantity = !Number.isNaN(amt) && amt !== 0 ? Math.abs(amt) : 0;
                                            endTradeRowRef.current = { symbol: pos.symbol || signalSymbol, positionSide, positionAmt: pos.positionAmt };
                                            setCloseTradePreview({ symbol, action: "Close Trade", positionSide, quantity });
                                          }}
                                          className="px-2 py-0.5 rounded bg-red-600 hover:bg-red-700 text-white font-semibold"
                                          title="End Trade"
                                        >
                                          Close Trade
                                        </button>
                                        <button
                                          type="button"
                                          disabled={exchangePositionData?.positions?.length >= 2 || hedgeSubmitting}
                                          onClick={() => {
                                            const sym = (pos.symbol || signalSymbol || "").toString().trim().toUpperCase();
                                            const positionSide = (pos.positionSide || "LONG").toString().toUpperCase();
                                            const amt = pos.positionAmt != null ? parseFloat(pos.positionAmt) : NaN;
                                            const qty = Number.isFinite(amt) && amt !== 0 ? Math.abs(amt) : 0;
                                            const oppositeSide = positionSide === "LONG" ? "SHORT" : "LONG";
                                            const orderSide = positionSide === "LONG" ? "SELL" : "BUY";
                                            setHedgePreview({
                                              symbol: sym,
                                              currentPositionSide: positionSide,
                                              oppositePositionSide: oppositeSide,
                                              orderSide,
                                              quantity: qty,
                                            });
                                          }}
                                          className="px-2 py-0.5 rounded bg-amber-600 hover:bg-amber-700 text-white font-semibold disabled:opacity-50 disabled:pointer-events-none disabled:cursor-not-allowed"
                                          title={hedgeSubmitting ? "Placing…" : exchangePositionData?.positions?.length >= 2 ? "Already hedged (LONG + SHORT)" : "Hedge"}
                                        >
                                          {hedgeSubmitting ? "…" : exchangePositionData?.positions?.length >= 2 ? "Hedged" : "Hedge"}
                                        </button>
                                        <div className="flex items-center gap-1">
                                          <input
                                            type="number"
                                            inputMode="decimal"
                                            step="any"
                                            value={stopPrice}
                                            onChange={(e) => setStopPrice(e.target.value)}
                                            placeholder="Stop"
                                            autoComplete="off"
                                            className="border border-gray-400 dark:border-gray-600 rounded px-1 py-0.5 bg-white dark:bg-[#222] w-25"
                                          />
                                          <button
                                            type="button"
                                            onClick={() => {
                                              const symbol = (pos.symbol || signalSymbol || "").toString().trim().toUpperCase();
                                              const positionSide = pos.positionSide ?? "BOTH";
                                              setStopPricePreview({ action: "Set Stop Price", symbol, positionSide, stopPrice: stopPrice.trim() });
                                            }}
                                            className="px-2 py-0.5 rounded bg-red-600 hover:bg-red-700 text-white font-semibold"
                                            title="Set Stop Price"
                                          >
                                            Set Stop Price
                                          </button>
                                        </div>
                                        <button
                                          type="button"
                                          onClick={() => {
                                            const symbol = (pos.symbol || signalSymbol || "").toString().trim().toUpperCase();
                                            const positionSide = pos.positionSide ?? "LONG";
                                            const notional = pos.notional != null ? parseFloat(pos.notional) : NaN;
                                            const entryPrice = pos.entryPrice != null ? parseFloat(pos.entryPrice) : NaN;
                                            const amt = pos.positionAmt != null ? parseFloat(pos.positionAmt) : 0;
                                            const oldQty = Math.abs(amt);
                                            const oldInvest = (!Number.isNaN(notional) && notional > 0) ? notional : (!Number.isNaN(entryPrice) && entryPrice > 0 && oldQty > 0 ? entryPrice * oldQty : 0);
                                            setAddInvNewQty(null);
                                            setAddInvestmentPreview({ symbol, positionSide, oldInvestment: oldInvest, oldQuantity: oldQty, newAmount: "" });
                                          }}
                                          className="px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
                                          title="Add Investment"
                                        >
                                          +Inv
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => {
                                            clearOrderSymbolRef.current = (pos.symbol || signalSymbol || "").toString().trim().toUpperCase();
                                            setActionModal({ open: true, type: "clear" });
                                          }}
                                          className="px-2 py-0.5 rounded bg-slate-600 hover:bg-slate-700 text-white font-semibold"
                                          title="Clear open orders (TP/SL) for this symbol — calls main_binance.closeOrder(symbol)"
                                        >
                                          Clear Order
                                        </button>
                                      </div>
                                    </td>
                                  );
                                }
                                const pl = parseFloat(pos.unRealizedProfit || 0);
                                const plClass = key === "unRealizedProfit" ? (pl < 0 ? "text-red-600 font-medium" : "text-green-600 font-medium") : "";
                                return (
                                  <td
                                    key={key}
                                    className={`border border-gray-200 dark:border-gray-700 px-2 py-1 ${plClass}`}
                                    style={{ fontSize: `${binanceFontSizePx}px` }}
                                  >
                                    {formatVal(key, pos[key])}
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : isExistInExchange && exchangePositionData?.ok ? (
                  <span className="text-gray-500 dark:text-white text-center">No open position for {signalSymbol}</span>
                ) : (
                  <span className="text-gray-500 dark:text-white text-center">Loading exchange data…</span>
                )}
              </div>
            </div>
          </div>
          <HeightDragger
            value={backDataHeight}
            min={SIZE_CONFIG.backData.min}
            max={SIZE_CONFIG.backData.max}
            onChange={setBackDataHeight}
            label="Drag to resize Binance Data section height"
          />
        </section>
          );
          return (
        <section key="chart" className="rounded-xl border border-gray-300 dark:border-gray-700 overflow-hidden shadow-lg flex-1 min-h-[240px] flex flex-col">
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 sm:px-4 py-2.5 bg-gradient-to-r from-teal-800 to-teal-700 text-white font-semibold flex-shrink-0">
            <span className="text-sm sm:text-base">Chart</span>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-white/90 text-xs">Height:</span>
              <div className="flex items-center gap-1" title="Chart height">
                <button
                  type="button"
                  onClick={() => setChartHeight((h) => Math.max(SIZE_CONFIG.chart.min, h - SIZE_CONFIG.chart.step))}
                  disabled={chartHeight <= SIZE_CONFIG.chart.min}
                  className="min-w-[32px] min-h-[32px] flex items-center justify-center rounded-lg bg-white/20 hover:bg-white/30 disabled:opacity-40 text-white text-lg font-bold"
                  aria-label="Decrease chart height"
                >
                  −
                </button>
                <button
                  type="button"
                  onClick={() => setChartHeight((h) => Math.min(SIZE_CONFIG.chart.max, h + SIZE_CONFIG.chart.step))}
                  disabled={chartHeight >= SIZE_CONFIG.chart.max}
                  className="min-w-[32px] min-h-[32px] flex items-center justify-center rounded-lg bg-white/20 hover:bg-white/30 disabled:opacity-40 text-white text-lg font-bold"
                  aria-label="Increase chart height"
                >
                  +
                </button>
              </div>
              <ZoomControls
                onDecrease={zoomOutChart}
                onIncrease={zoomInChart}
                current={zoomChart}
                label="Zoom chart labels"
              />
            </div>
          </div>
          <div className="p-3 sm:p-4 flex-1 min-h-0 overflow-auto overflow-x-auto" style={{ fontSize: `${(zoomChart / 100) * 14}px`, minHeight: chartHeight }}>
            <LiveTradeChartSection
              tradePair={tradePair}
              chartSize={chartSize}
              alertRules={alertRules}
              setAlertRules={setAlertRules}
              alertRuleGroups={alertRuleGroups}
              setAlertRuleGroups={setAlertRuleGroups}
              masterBlinkColor={masterBlinkColor}
              setMasterBlinkColor={setMasterBlinkColor}
              showAlertSettings={showAlertSettings}
              setShowAlertSettings={setShowAlertSettings}
            />
          </div>
          <HeightDragger
            value={chartHeight}
            min={SIZE_CONFIG.chart.min}
            max={SIZE_CONFIG.chart.max}
            onChange={setChartHeight}
            label="Drag to resize Chart section height"
          />
        </section>
          );
        })}
      </div>

      {showInfoSettings && (
        <InfoFieldsModal
          orderedKeys={orderedKeys}
          allKeys={allKeys}
          visibleKeys={visibleKeys}
          setVisibleKeys={setVisibleKeys}
          setFieldOrder={setFieldOrder}
          onClose={() => setShowInfoSettings(false)}
        />
      )}
      {showLayoutSettings && (
        <SectionOrderModal
          sectionOrder={sectionOrder}
          setSectionOrder={setSectionOrder}
          onClose={() => setShowLayoutSettings(false)}
        />
      )}
      {closeTradePreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => { setCloseTradePreview(null); endTradeRowRef.current = null; }}>
          <div
            className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-sm w-full shadow-xl border border-gray-200 dark:border-gray-700"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-semibold text-lg mb-4 text-gray-900 dark:text-white">Confirm close position</h3>
            <div className="space-y-3 mb-6">
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Action</span>
                <span className="font-medium text-gray-900 dark:text-white">{closeTradePreview.action}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Symbol</span>
                <span className="font-medium text-gray-900 dark:text-white">{closeTradePreview.symbol}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Position side</span>
                <span className="font-medium text-gray-900 dark:text-white">{closeTradePreview.positionSide}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Quantity</span>
                <span className="font-medium text-gray-900 dark:text-white">{closeTradePreview.quantity}</span>
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => { setCloseTradePreview(null); endTradeRowRef.current = null; }}
                className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-600 text-gray-800 dark:text-white font-medium hover:bg-gray-300 dark:hover:bg-gray-500"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  setActionModal({ open: true, type: "endTrade", positionSide: closeTradePreview.positionSide });
                  setCloseTradePreview(null);
                }}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white font-medium"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
      {hedgePreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setHedgePreview(null)}>
          <div
            className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-md w-full shadow-xl border border-gray-200 dark:border-gray-700"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-semibold text-lg mb-4 text-gray-900 dark:text-white">Execute opposite trade (Hedge)</h3>
            <p className="text-sm text-amber-700 dark:text-amber-400 mb-4">
              You have <strong>{hedgePreview.currentPositionSide}</strong>. We will place <strong>{hedgePreview.oppositePositionSide}</strong> ({hedgePreview.orderSide}) with same quantity.
            </p>
            <div className="space-y-3 mb-4">
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Symbol</span>
                <span className="font-medium text-gray-900 dark:text-white">{hedgePreview.symbol}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Current position side</span>
                <span className="font-medium text-gray-900 dark:text-white">{hedgePreview.currentPositionSide}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Opposite position side</span>
                <span className="font-medium text-emerald-600 dark:text-emerald-400">{hedgePreview.oppositePositionSide} ({hedgePreview.orderSide})</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Quantity</span>
                <span className="font-medium text-gray-900 dark:text-white">{hedgePreview.quantity}</span>
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setHedgePreview(null)}
                className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-600 text-gray-800 dark:text-white font-medium hover:bg-gray-300 dark:hover:bg-gray-500"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  hedgeRowRef.current = {
                    symbol: hedgePreview.symbol,
                    positionSide: hedgePreview.currentPositionSide,
                    quantity: hedgePreview.quantity,
                  };
                  setActionModal({
                    open: true,
                    type: "hedge",
                    hedgeSummary: `${hedgePreview.symbol} ${hedgePreview.oppositePositionSide} qty ${hedgePreview.quantity}`,
                  });
                  setHedgePreview(null);
                }}
                className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
      {executePreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setExecutePreview(null)}>
          <div
            className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-md w-full shadow-xl border border-gray-200 dark:border-gray-700"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-semibold text-lg mb-4 text-gray-900 dark:text-white">Execute Trade in Exchange</h3>
            <div className="space-y-3 mb-4">
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Symbol</span>
                <span className="font-medium text-gray-900 dark:text-white">{executePreview.symbol}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Back Invest (USDT)</span>
                <span className="font-medium text-gray-900 dark:text-white">{(executePreview.backInvest || 0).toFixed(2)}</span>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-gray-500 dark:text-gray-400 whitespace-nowrap">Live Invest (USDT)</label>
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  min="0"
                  value={executePreview.liveInvest}
                  onChange={(e) => setExecutePreview((p) => p ? { ...p, liveInvest: e.target.value.trim() } : null)}
                  placeholder="0"
                  autoComplete="off"
                  className="flex-1 border border-gray-400 dark:border-gray-600 rounded px-2 py-1.5 bg-white dark:bg-[#333] text-gray-900 dark:text-white"
                />
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Stop price</span>
                <span className="font-medium text-gray-900 dark:text-white">{executePreview.stopPrice || "\u2014"}</span>
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setExecutePreview(null)}
                className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-600 text-gray-800 dark:text-white font-medium hover:bg-gray-300 dark:hover:bg-gray-500"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!executePreview.liveInvest || parseFloat(executePreview.liveInvest) <= 0}
                onClick={() => {
                  executeRowRef.current = {
                    symbol: executePreview.symbol,
                    amount: executePreview.liveInvest.trim(),
                    stop_price: executePreview.stopPrice.trim(),
                  };
                  setActionModal({ open: true, type: "execute" });
                  setExecutePreview(null);
                }}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
      {addInvestmentPreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => { setAddInvestmentPreview(null); setAddInvNewQty(null); }}>
          <div
            className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-md w-full shadow-xl border border-gray-200 dark:border-gray-700"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-semibold text-lg mb-4 text-gray-900 dark:text-white">Add Investment</h3>
            <div className="space-y-3 mb-4">
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Symbol</span>
                <span className="font-medium text-gray-900 dark:text-white">{addInvestmentPreview.symbol}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Position side</span>
                <span className="font-medium text-gray-900 dark:text-white">{addInvestmentPreview.positionSide}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Old investment (USDT)</span>
                <span className="font-medium text-gray-900 dark:text-white">{(addInvestmentPreview.oldInvestment || 0).toFixed(2)}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Old quantity</span>
                <span className="font-medium text-gray-900 dark:text-white">{(addInvestmentPreview.oldQuantity || 0).toFixed(4)}</span>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-gray-500 dark:text-gray-400 whitespace-nowrap">New investment (USDT)</label>
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  min="0"
                  value={addInvestmentPreview.newAmount}
                  onChange={(e) => setAddInvestmentPreview((p) => p ? { ...p, newAmount: e.target.value.trim() } : null)}
                  placeholder="0"
                  autoComplete="off"
                  className="flex-1 border border-gray-400 dark:border-gray-600 rounded px-2 py-1.5 bg-white dark:bg-[#333] text-gray-900 dark:text-white"
                />
              </div>
              {addInvestmentPreview.newAmount && (
                <>
                  <div className="flex justify-between gap-4">
                    <span className="text-gray-500 dark:text-gray-400">Total investment (USDT)</span>
                    <span className="font-medium text-emerald-600 dark:text-emerald-400">
                      {(parseFloat(addInvestmentPreview.oldInvestment || 0) + parseFloat(addInvestmentPreview.newAmount || 0)).toFixed(2)}
                    </span>
                  </div>
                  <div className="flex justify-between gap-4">
                    <span className="text-gray-500 dark:text-gray-400">New quantity</span>
                    <span className="font-medium text-gray-900 dark:text-white">
                      {addInvNewQty != null ? addInvNewQty.toFixed(4) : "…"}
                    </span>
                  </div>
                  <div className="flex justify-between gap-4">
                    <span className="text-gray-500 dark:text-gray-400">Total quantity</span>
                    <span className="font-medium text-emerald-600 dark:text-emerald-400">
                      {addInvNewQty != null
                        ? ((addInvestmentPreview.oldQuantity || 0) + addInvNewQty).toFixed(4)
                        : "…"}
                    </span>
                  </div>
                </>
              )}
            </div>
            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => { setAddInvestmentPreview(null); setAddInvNewQty(null); }}
                className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-600 text-gray-800 dark:text-white font-medium hover:bg-gray-300 dark:hover:bg-gray-500"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!addInvestmentPreview.newAmount || parseFloat(addInvestmentPreview.newAmount) <= 0}
                onClick={() => {
                  addInvestmentRowRef.current = {
                    symbol: addInvestmentPreview.symbol,
                    positionSide: addInvestmentPreview.positionSide,
                    amount: addInvestmentPreview.newAmount.trim(),
                  };
                  setActionModal({ open: true, type: "addInvestment" });
                  setAddInvestmentPreview(null);
                  setAddInvNewQty(null);
                }}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
      {stopPricePreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setStopPricePreview(null)}>
          <div
            className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-sm w-full shadow-xl border border-gray-200 dark:border-gray-700"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-semibold text-lg mb-4 text-gray-900 dark:text-white">Confirm set stop price</h3>
            <div className="space-y-3 mb-6">
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Action</span>
                <span className="font-medium text-gray-900 dark:text-white">{stopPricePreview.action}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Symbol</span>
                <span className="font-medium text-gray-900 dark:text-white">{stopPricePreview.symbol}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Position side</span>
                <span className="font-medium text-gray-900 dark:text-white">{stopPricePreview.positionSide}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-500 dark:text-gray-400">Stop price</span>
                <span className="font-medium text-gray-900 dark:text-white">{stopPricePreview.stopPrice || "\u2014"}</span>
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setStopPricePreview(null)}
                className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-600 text-gray-800 dark:text-white font-medium hover:bg-gray-300 dark:hover:bg-gray-500"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!stopPricePreview.stopPrice}
                onClick={() => {
                  setStopPriceRowRef.current = { symbol: stopPricePreview.symbol, positionSide: stopPricePreview.positionSide, stopPrice: stopPricePreview.stopPrice };
                  setActionModal({ open: true, type: "setStopPrice", stopPrice: stopPricePreview.stopPrice });
                  setStopPricePreview(null);
                }}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
      <ConfirmActionModal
        open={actionModal.open}
        onClose={() => {
          if (actionModal.type === "endTrade") endTradeRowRef.current = null;
          if (actionModal.type === "setStopPrice") setStopPriceRowRef.current = null;
          if (actionModal.type === "addInvestment") addInvestmentRowRef.current = null;
          if (actionModal.type === "execute") executeRowRef.current = null;
          if (actionModal.type === "hedge") hedgeRowRef.current = null;
          if (actionModal.type === "clear") clearOrderSymbolRef.current = null;
          setActionModal({ open: false, type: null });
        }}
        actionType={actionModal.type}
        requireAmount={false}
        amountLabel={actionModal.type === "execute" ? "Amount" : "Investment amount"}
        amountPlaceholder={actionModal.type === "execute" ? "0" : "0"}
        extraLabel={actionModal.type === "setStopPrice" ? "Stop price" : actionModal.type === "autoPilot" ? "Action" : actionModal.type === "endTrade" ? "Position side" : actionModal.type === "hedge" ? "Hedge" : undefined}
        extraValue={actionModal.type === "setStopPrice" ? (actionModal.stopPrice ?? stopPrice) : actionModal.type === "autoPilot" ? (actionModal.autoEnable ? "enable" : "disable") : actionModal.type === "endTrade" ? (actionModal.positionSide || "BOTH") : actionModal.type === "hedge" ? actionModal.hedgeSummary : undefined}
        onConfirm={actionModal.type ? getConfirmHandler(actionModal.type) : undefined}
      />
    </div>
  );
}
