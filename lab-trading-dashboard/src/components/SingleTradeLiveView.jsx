import React, { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Play, Settings, Square, Shield, Crosshair, LayoutGrid } from "lucide-react";
import { formatTradeData } from "./TableView";
import { LogoutButton } from "../auth";
import { API_BASE_URL, api } from "../config";

const REFRESH_INTERVAL_KEY = "refresh_app_main_intervalSec";

const TV_SCRIPT_ID = "tradingview-widget-script-single";
function loadTradingViewScript() {
  if (!document.getElementById(TV_SCRIPT_ID)) {
    const script = document.createElement("script");
    script.id = TV_SCRIPT_ID;
    script.src = "https://s3.tradingview.com/tv.js";
    script.async = true;
    document.body.appendChild(script);
  }
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

const INDICATORS = [
  { key: "RSI@tv-basicstudies", label: "RSI-9" },
  { key: "MACD@tv-basicstudies", label: "MACD" },
  { key: "Volume@tv-basicstudies", label: "Volume" },
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
const SECTION_IDS = ["information", "binanceData", "chart"];
const SECTION_LABELS = { information: "Information", binanceData: "Binance Data", chart: "Chart" };

// Signals grid: only these rows (label = display, key = API response key)
const SIGNAL_ROWS = [
  { label: "INSTITUTIONAL_SIGNAL", key: "INSTITUTIONAL_SIGNAL" },
  { label: "BB FLAT", key: "bb_flat_market" },
  { label: "BB FLAT SIGNAL", key: "bb_flat_signal" },
  { label: "RSI_9", key: "RSI_9" },
  { label: "Divergence", key: "Divergence" },
  { label: "DIVERGEN_SIGNAL_LIVE", key: "DIVERGEN_SIGNAL_LIVE" },
  { label: "RSI_DIVERGENCE_LIVE", key: "RSI_DIVERGENCE_LIVE" },
  { label: "TAKEACTION", key: "TAKEACTION" },
  { label: "CCI Exit Cross", key: "CCI_Exit_Cross" },
  { label: "MACD Color Signal", key: "macd_color_signal" },
  { label: "CCI Entry State 100", key: "CCI_Entry_State_100" },
  { label: "CCI SMA 100", key: "CCI_SMA_100" },
  { label: "CCI Entry State 9", key: "CCI_Entry_State_9" },
  { label: "CCI SMA 9", key: "CCI_SMA_9" },
  { label: "cci_value_100", key: "cci_value_100" },
  { label: "cci_value_9", key: "cci_value_9" },
  { label: "Lower MACD Color Signa", key: "lower_MACD_Color_Signal" },
  { label: "Andean Oscillator", key: "Andean_Oscillator" },
  { label: "Candle Henkin Color", key: "Candle_Henkin_Color" },
  { label: "Candle Regular Color", key: "color" },
  { label: "EMA 5 8 Cross", key: "EMA_5_8_Cross" },
  { label: "ZLEMA Bullish Entry", key: "zlema_bullish_entry" },
  { label: "ZLEMA Bearish Entry", key: "zlema_bearish_entry" },
  { label: "Volume Ratio", key: "Volume_Ratio" },
  { label: "OB_SIGNAL", key: "OB_SIGNAL" },
  { label: "candle_pattern_signal", key: "candle_pattern_signal" },
  { label: "Henkin Candle Pattern Signal", key: "Henkin_Candle_Pattern_Signal" },
  { label: "TDFI 2 EMA", key: "TDFI_2_EMA" },
  { label: "TDFI State", key: "TDFI_State" },
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

// Demo: replace with real auth; for now accept this or any non-empty for testing
const DEMO_PASSWORD = "demo123";
const ACTION_LABELS = {
  execute: "Execute trade",
  endTrade: "End trade",
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
    // Demo: accept DEMO_PASSWORD or any for testing; replace with real auth
    if (DEMO_PASSWORD && p !== DEMO_PASSWORD) {
      setError("Invalid password");
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
    setError("");
    try {
      const payload = { password: (password || "").trim() };
      if (requireAmount) payload.amount = amount.trim();
      if (extraValue !== undefined) payload.extraValue = extraValue;
      await (onConfirm && onConfirm(payload));
      setSuccess(true);
      setTimeout(handleClose, 1500);
    } catch (e) {
      setError(e?.message || "Failed");
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
          <p className="text-green-600 dark:text-green-400 font-medium mb-4">Success!</p>
        )}
        {!showSuccess && showPasswordStep && (
          <>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setError(""); }}
              placeholder="Password"
              className="w-full border-2 border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-[#333] text-[#222] dark:text-gray-200 mb-3"
              autoFocus
            />
            {extraLabel && extraValue != null && (
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">{extraLabel}: {extraValue}</p>
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
              placeholder={amountPlaceholder}
              className="w-full border-2 border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-[#333] text-[#222] dark:text-gray-200 mb-3"
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
              <button type="button" onClick={handlePasswordNext} className="px-4 py-1.5 rounded-lg bg-teal-600 text-white">
                {requireAmount ? "Next" : "Confirm"}
              </button>
            )}
            {showAmountStep && (
              <>
                <button type="button" onClick={() => setStep("password")} className="px-3 py-1.5 rounded-lg bg-gray-200 dark:bg-gray-700">
                  Back
                </button>
                <button type="button" onClick={handleAmountConfirm} className="px-4 py-1.5 rounded-lg bg-teal-600 text-white">
                  Confirm
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
  backRight: "singleTradeLiveView_zoom_backRight",
  chart: "singleTradeLiveView_zoom_chart",
};
const ZOOM_CONFIG = { default: 100, min: 70, max: 150, step: 10 };

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
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
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
              <span className="text-gray-400 select-none" title="Drag to reorder">⋮⋮</span>
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
    const next = [...sectionOrder];
    const [removed] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, removed);
    setSectionOrder(next);
  };
  const handleDragEnd = () => {
    setDragIndex(null);
    setOverIndex(null);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-md w-full shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-semibold text-lg mb-2">Section order</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Drag to set the order of sections (top to bottom).
        </p>
        <ul className="space-y-1">
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
              <span className="text-gray-400 select-none" title="Drag to reorder">⋮⋮</span>
              <span className="font-medium">{SECTION_LABELS[id] || id}</span>
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

function LiveTradeChartSection({ tradePair, chartSize = { width: 500, height: 400 } }) {
  const symbols = [getRobustSymbol(tradePair), "BTCUSDT"];
  const getSetting = (key, def) => {
    try {
      const v = localStorage.getItem(`chartGridSetting_${key}`);
      if (v !== null) return JSON.parse(v);
    } catch {}
    return def;
  };
  const [interval, setInterval] = useState(getSetting("interval", "15m"));
  const [showAllIntervals, setShowAllIntervals] = useState(false);
  const [layout, setLayout] = useState(2); // 1 or 2 per row
  const [intervalOrder, setIntervalOrder] = useState(() => {
    try {
      const v = localStorage.getItem(INTERVAL_ORDER_KEY);
      if (v) return JSON.parse(v);
    } catch {}
    return [...ALL_INTERVALS];
  });
  const [showIntervalOrderModal, setShowIntervalOrderModal] = useState(false);
  const [indicators, setIndicators] = useState(getSetting("indicators", ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"]));
  const [source] = useState(getSetting("source", "tradingview"));

  useEffect(() => {
    if (source === "tradingview") loadTradingViewScript();
  }, [source]);

  useEffect(() => {
    try {
      localStorage.setItem(INTERVAL_ORDER_KEY, JSON.stringify(intervalOrder));
    } catch {}
  }, [intervalOrder]);

  const intervalsToShow = showAllIntervals ? intervalOrder : [interval];

  // Only recreate charts when these actual values change (not on every parent re-render).
  // Using primitives/stable keys avoids effect running when unrelated state (section order,
  // zoom, split %, etc.) changes in the parent.
  const chartHeight = chartSize?.height ?? 400;
  const chartWidth = chartSize?.width ?? 500;
  const intervalOrderKey = intervalOrder.join(",");
  const symbolsKey = symbols.join(",");

  useEffect(() => {
    if (source !== "tradingview" || !window.TradingView) return;
    const list = showAllIntervals ? intervalOrder : [interval];
    symbols.forEach((symbol) => {
      list.forEach((intv) => {
        const safeIntv = intv.replace(/[^a-z0-9]/gi, "_");
        const cid = `single_tv_${symbol}_${safeIntv}`;
        const container = document.getElementById(cid);
        if (container) {
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
              volumePaneSize: indicators.includes("Volume@tv-basicstudies") ? "medium" : "0",
              paneProperties: { topMargin: 10, bottomMargin: 15, rightMargin: 20 },
              scalesProperties: { fontSize: 11 },
            },
            studies_overrides: { "RSI@tv-basicstudies.length": 9 },
            hide_side_toolbar: false,
            allow_symbol_change: false,
            details: true,
            withdateranges: true,
            hideideas: true,
            toolbar_bg: "#222",
            height: chartHeight,
            width: chartWidth,
          });
        }
      });
    });
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

      <div className="space-y-6">
        {intervalsToShow.map((intv) => (
          <div
            key={intv}
            className="grid gap-4"
            style={{ gridTemplateColumns: `repeat(${layout}, minmax(0, 1fr))` }}
          >
            {symbols.map((symbol) => {
              const safeIntv = intv.replace(/[^a-z0-9]/gi, "_");
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
  const row = formattedRow || {};
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
      return 20;
    })();
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/trades`);
        if (cancelled || !res.ok) return;
        const data = await res.json();
        if (cancelled || !Array.isArray(data)) return;
        const trade = data.find(
          (t) =>
            (t.unique_id != null && String(t.unique_id) === uniqueId) ||
            (t.Unique_ID != null && String(t.Unique_ID) === uniqueId)
        );
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
  const tradePair = rawTrade?.pair || stripHtml(row.Pair) || "";
  const signalSymbol = getRobustSymbol(tradePair);
  const [signalsData, setSignalsData] = useState(null);
  const SIGNAL_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes
  useEffect(() => {
    if (!signalSymbol) return;
    const callCalculateSignals = async () => {
      try {
        const res = await fetch(api("/api/calculate-signals"), {
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

  const [showInfoSettings, setShowInfoSettings] = useState(false);
  const [showLayoutSettings, setShowLayoutSettings] = useState(false);
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
  const [backSplitPercent, setBackSplitPercent] = useState(() => {
    try {
      const v = localStorage.getItem(BACK_SPLIT_KEY);
      if (v != null) {
        const n = parseInt(v, 10);
        if (!Number.isNaN(n)) return Math.max(20, Math.min(80, n));
      }
    } catch {}
    return 50;
  });
  useEffect(() => {
    localStorage.setItem(INFO_SPLIT_KEY, String(infoSplitPercent));
  }, [infoSplitPercent]);
  useEffect(() => {
    localStorage.setItem(BACK_SPLIT_KEY, String(backSplitPercent));
  }, [backSplitPercent]);

  const [zoomInfoLeft, zoomOutInfoLeft, zoomInInfoLeft] = useZoomLevel(ZOOM_KEYS.infoLeft);
  const [zoomInfoGrid, zoomOutInfoGrid, zoomInInfoGrid] = useZoomLevel(ZOOM_KEYS.infoGrid);
  const [zoomBackLeft, zoomOutBackLeft, zoomInBackLeft] = useZoomLevel(ZOOM_KEYS.backLeft);
  const [zoomBackRight, zoomOutBackRight, zoomInBackRight] = useZoomLevel(ZOOM_KEYS.backRight);
  const [zoomChart, zoomOutChart, zoomInChart] = useZoomLevel(ZOOM_KEYS.chart);

  useEffect(() => {
    if (fieldOrder && fieldOrder.length) {
      try {
        localStorage.setItem(INFO_FIELD_ORDER_KEY, JSON.stringify(fieldOrder));
      } catch {}
    }
  }, [fieldOrder]);
  useEffect(() => {
    if (visibleKeys && visibleKeys.size > 0) {
      try {
        localStorage.setItem(INFO_FIELDS_KEY, JSON.stringify([...visibleKeys]));
      } catch {}
    }
  }, [visibleKeys]);
  useEffect(() => {
    try {
      localStorage.setItem(SECTION_ORDER_KEY, JSON.stringify(sectionOrder));
    } catch {}
  }, [sectionOrder]);

  const chartSize = { width: 500, height: chartHeight };

  // Call Python backend API (backend must expose these endpoints, e.g. Flask/FastAPI)
  const callPythonApi = useCallback(async (endpoint, body) => {
    const res = await fetch(api(endpoint), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.message || err.detail || `API error ${res.status}`);
    }
    return res.json().catch(() => ({}));
  }, []);

  const handleExecute = useCallback(async ({ password, amount }) => {
    await callPythonApi("/api/execute", {
      unique_id: rawTrade?.unique_id,
      amount: amount?.trim(),
      password,
    });
  }, [rawTrade?.unique_id, callPythonApi]);
  const handleEndTrade = useCallback(async ({ password }) => {
    await callPythonApi("/api/end-trade", {
      unique_id: rawTrade?.unique_id,
      password,
    });
  }, [rawTrade?.unique_id, callPythonApi]);
  const handleHedge = useCallback(async ({ password }) => {
    await callPythonApi("/api/hedge", {
      unique_id: rawTrade?.unique_id,
      password,
    });
  }, [rawTrade?.unique_id, callPythonApi]);
  const handleSetStopPrice = useCallback(async ({ password, extraValue }) => {
    await callPythonApi("/api/stop-price", {
      unique_id: rawTrade?.unique_id,
      stop_price: extraValue,
      password,
    });
  }, [rawTrade?.unique_id, callPythonApi]);
  const handleAddInvestment = useCallback(async ({ password, amount }) => {
    await callPythonApi("/api/add-investment", {
      unique_id: rawTrade?.unique_id,
      amount: amount?.trim(),
      password,
    });
  }, [rawTrade?.unique_id, callPythonApi]);
  const handleClear = useCallback(async ({ password }) => {
    await callPythonApi("/api/clear", {
      unique_id: rawTrade?.unique_id,
      password,
    });
  }, [rawTrade?.unique_id, callPythonApi]);

  const getConfirmHandler = useCallback((type) => {
    switch (type) {
      case "execute": return handleExecute;
      case "endTrade": return handleEndTrade;
      case "hedge": return handleHedge;
      case "setStopPrice": return handleSetStopPrice;
      case "addInvestment": return handleAddInvestment;
      case "clear": return handleClear;
      default: return async () => {};
    }
  }, [handleExecute, handleEndTrade, handleHedge, handleSetStopPrice, handleAddInvestment, handleClear]);

  return (
    <div className="fixed inset-0 flex flex-col bg-[#f5f6fa] dark:bg-[#0f0f0f] text-[#222] dark:text-gray-200 overflow-hidden w-full">
      <div className="flex-none flex items-center justify-between gap-2 px-3 sm:px-4 py-2 bg-[#181818] text-white border-b border-gray-700 shadow-md">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 font-medium transition-colors min-h-[40px] shrink-0"
        >
          ← Back
        </button>
        <span className="font-semibold text-base sm:text-lg truncate">Live Trade — {stripHtml(row.Pair) || "N/A"}</span>
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
                onClick={() => setActionModal({ open: true, type: "execute" })}
                className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-emerald-500 via-green-500 to-teal-500 hover:from-emerald-600 hover:via-green-600 hover:to-teal-600 text-white text-lg font-bold shadow-lg shadow-emerald-500/40 hover:shadow-emerald-500/50 hover:scale-105 active:scale-100 transition-all min-h-[48px] border-2 border-emerald-400/50"
              >
                <Play size={24} fill="currentColor" />
                Execute
              </button>
            </div>
          </div>
          <div className="flex min-h-0 p-3 sm:p-4 gap-0 flex-shrink-0" style={{ height: infoGridHeight }}>
            <div
              className="border border-gray-300 dark:border-gray-600 rounded-xl flex flex-col overflow-hidden flex-shrink-0 bg-white dark:bg-[#0d0d0d]"
              style={{ width: `${infoSplitPercent}%`, minHeight: infoLeftHeight, fontSize: `${(zoomInfoLeft / 100) * 11}px` }}
            >
              <div className="flex items-center gap-2 p-1.5 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
                <ZoomControls
                  onDecrease={zoomOutInfoLeft}
                  onIncrease={zoomInInfoLeft}
                  current={zoomInfoLeft}
                  label="Zoom"
                  className="min-w-[28px] min-h-[28px] flex items-center justify-center rounded bg-gray-300 hover:bg-gray-400 dark:bg-gray-600 dark:hover:bg-gray-500 disabled:opacity-40 text-gray-800 dark:text-white text-xs font-bold"
                />
                <span className="text-xs font-semibold text-gray-600 dark:text-gray-400 truncate">
                  {signalsData?.symbol || signalSymbol || "—"} signals
                </span>
              </div>
              <div className="flex-1 min-h-0 overflow-auto">
                {signalsData?.ok && signalsData?.intervals ? (
                  (() => {
                    const INTERVALS = ["5m", "15m", "1h", "4h"];
                    const ROW_LABELS = ["prior row", "prev row", "current_row"];
                    return (
                      <table className="w-full border-collapse text-[10px] sm:text-xs">
                        <thead className="sticky top-0 bg-gray-100 dark:bg-gray-800 z-10">
                          <tr>
                            <th className="border border-gray-300 dark:border-gray-600 px-1 py-0.5 text-left font-semibold text-gray-700 dark:text-gray-300 whitespace-nowrap min-w-[80px]">Signal</th>
                            {INTERVALS.flatMap((iv) =>
                              ROW_LABELS.map((label) => (
                                <th key={`${iv}-${label}`} className="border border-gray-300 dark:border-gray-600 px-0.5 py-0.5 text-center font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">
                                  {iv} {label}
                                </th>
                              ))
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {SIGNAL_ROWS.map(({ label, key }) => (
                            <tr key={key} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                              <td className="border border-gray-200 dark:border-gray-600 px-1 py-0.5 font-medium text-teal-700 dark:text-teal-400 whitespace-nowrap truncate max-w-[100px]" title={label}>
                                {label}
                              </td>
                              {INTERVALS.flatMap((iv) => {
                                const summary = signalsData.intervals[iv]?.summary;
                                const rows = Array.isArray(summary) ? summary : [];
                                return [0, 1, 2].map((rowIdx) => {
                                  const v = rows[rowIdx]?.[key];
                                  const str = v != null ? (typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed?.(4) ?? String(v)) : String(v)) : "—";
                                  return (
                                    <td key={`${iv}-${rowIdx}`} className="border border-gray-200 dark:border-gray-600 px-0.5 py-0.5 text-center text-gray-800 dark:text-gray-200 truncate max-w-[60px]" title={str}>
                                      {str}
                                    </td>
                                  );
                                });
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    );
                  })()
                ) : (
                  <div className="flex items-center justify-center h-full text-gray-500 dark:text-gray-400 text-center p-2">Loading signals…</div>
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
                    <div className="text-[10px] sm:text-xs font-semibold uppercase tracking-wide text-teal-700 dark:text-teal-400 mb-1 truncate" title={key.replace(/_/g, " ")}>
                      {key.replace(/_/g, " ")}
                    </div>
                    <div className="font-medium text-[#222] dark:text-gray-200 break-words leading-snug max-h-14 overflow-hidden" style={{ fontSize: "1em" }} title={stripHtml(row[key])}>
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
        <section key="binanceData" className="rounded-xl border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#181a20] overflow-hidden shadow-lg flex-shrink-0 flex flex-col">
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 sm:px-4 py-2.5 bg-gradient-to-r from-teal-800 to-teal-700 text-white font-semibold flex-shrink-0">
            <span className="text-sm sm:text-base">Binance Data</span>
          </div>
          <div
            className="flex min-h-0 p-3 sm:p-4 gap-0 flex-shrink-0"
            style={{ height: backDataHeight }}
          >
            <div
              className="border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-xl flex flex-col items-center justify-center text-gray-500 bg-gray-50 dark:bg-[#0d0d0d] overflow-hidden flex-shrink-0"
              style={{ width: `${backSplitPercent}%`, minHeight: backLeftHeight, fontSize: `${(zoomBackLeft / 100) * 14}px` }}
            >
              <div className="flex items-center gap-2 mb-2 flex-wrap justify-center">
                <span>(Empty — for future use)</span>
                <ZoomControls
                  onDecrease={zoomOutBackLeft}
                  onIncrease={zoomInBackLeft}
                  current={zoomBackLeft}
                  label="Zoom left"
                  className="min-w-[32px] min-h-[32px] flex items-center justify-center rounded-lg bg-gray-300 hover:bg-gray-400 dark:bg-gray-600 dark:hover:bg-gray-500 disabled:opacity-40 text-gray-800 dark:text-white text-xs font-bold"
                />
              </div>
            </div>
            <WidthDragger leftPercent={backSplitPercent} onChange={setBackSplitPercent} min={20} max={80} />
            <div className="min-w-0 flex-1 flex flex-wrap items-center gap-3 sm:gap-4 overflow-auto" style={{ width: `${100 - backSplitPercent}%`, fontSize: `${(zoomBackRight / 100) * 14}px` }}>
              <div className="flex items-center gap-2 flex-wrap">
                <ZoomControls
                  onDecrease={zoomOutBackRight}
                  onIncrease={zoomInBackRight}
                  current={zoomBackRight}
                  label="Zoom buttons"
                  className="min-w-[32px] min-h-[32px] flex items-center justify-center rounded-lg bg-teal-700/80 hover:bg-teal-600 text-white text-xs font-bold disabled:opacity-40"
                />
                <button
                  type="button"
                  onClick={() => setActionModal({ open: true, type: "endTrade" })}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-600 hover:bg-red-700 text-white font-semibold shadow-md hover:shadow-lg transition-all border border-red-500/50"
                >
                  <Square size={18} />
                  End Trade
                </button>
                <button
                  type="button"
                  onClick={() => setActionModal({ open: true, type: "hedge" })}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-700 text-white font-semibold shadow-md hover:shadow-lg transition-all border border-amber-500/50"
                >
                  <Shield size={18} />
                  Hedge
                </button>
                <div className="inline-flex items-center gap-2 flex-wrap">
                  <label className="font-medium text-[#222] dark:text-gray-200">Stop price:</label>
                  <input
                    type="text"
                    value={stopPrice}
                    onChange={(e) => setStopPrice(e.target.value)}
                    placeholder="Price"
                    className="border-2 border-gray-400 dark:border-gray-600 rounded-lg px-3 py-1.5 bg-white dark:bg-[#222] text-[#222] dark:text-white w-28 font-medium"
                  />
                  <button
                    type="button"
                    onClick={() => setActionModal({ open: true, type: "setStopPrice" })}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-600 hover:bg-gray-700 text-white font-medium shadow transition-all"
                  >
                    <Crosshair size={16} />
                    Set
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => setActionModal({ open: true, type: "addInvestment" })}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold shadow-md hover:shadow-lg transition-all border border-emerald-500/50"
                >
                  Add Investment
                </button>
                <button
                  type="button"
                  onClick={() => setActionModal({ open: true, type: "clear" })}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-600 hover:bg-slate-700 text-white font-semibold shadow-md hover:shadow-lg transition-all border border-slate-500/50"
                >
                  Clear
                </button>
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
            <ZoomControls
              onDecrease={zoomOutChart}
              onIncrease={zoomInChart}
              current={zoomChart}
              label="Zoom chart labels"
            />
          </div>
          <div className="p-3 sm:p-4 flex-1 min-h-0 overflow-auto overflow-x-auto" style={{ fontSize: `${(zoomChart / 100) * 14}px`, minHeight: chartHeight }}>
            <LiveTradeChartSection tradePair={tradePair} chartSize={chartSize} />
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
      <ConfirmActionModal
        open={actionModal.open}
        onClose={() => setActionModal({ open: false, type: null })}
        actionType={actionModal.type}
        requireAmount={actionModal.type === "execute" || actionModal.type === "addInvestment"}
        amountLabel={actionModal.type === "execute" ? "Amount" : "Investment amount"}
        amountPlaceholder={actionModal.type === "execute" ? "0" : "0"}
        extraLabel={actionModal.type === "setStopPrice" ? "Stop price" : undefined}
        extraValue={actionModal.type === "setStopPrice" ? stopPrice : undefined}
        onConfirm={actionModal.type ? getConfirmHandler(actionModal.type) : undefined}
      />
    </div>
  );
}
