import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import moment from "moment";
import * as XLSX from "xlsx";
import TradeFilterPanel from "./components/TradeFilterPanel";
import DashboardCard from './components/DashboardCard';  // adjust path if needed
import TableView from "./components/TableView";
import Sidebar from "./components/Sidebar";
import ChartGrid from "./components/ChartGrid";
import { Routes, Route } from "react-router-dom";
import ChartGridPage from "./components/ChartGridPage";
import CustomChartGrid from "./components/CustomChartGrid";
import PairStatsGrid from "./components/PairStatsGrid";
// import SettingsPage from './components/SettingsPage';
import ReportDashboard from './components/ReportDashboard';
import ListViewPage from './components/ListViewPage';
import LiveTradeViewPage from './components/LiveTradeViewPage';
import LiveRunningTradesPage from './components/LiveRunningTradesPage';
import LoginPage from './components/LoginPage';
import { checkSession, logoutApi, AuthContext, LogoutButton } from './auth';

import GroupViewPage from './pages/GroupViewPage';
import RefreshControls from './components/RefreshControls';
import SuperTrendPanel from "./SuperTrendPanel";
import TradeComparePage from "./components/TradeComparePage";
import SoundSettings from "./components/SoundSettings";
import { API_BASE_URL, getApiBaseUrl, api, apiFetch, loadRuntimeApiConfig, isLocalhostOrigin, getLocalhostUseCloudFallback } from "./config";

// Animated SVG background for LAB title
function AnimatedGraphBackground({ width = 400, height = 80, opacity = 0.4 }) {
  // Two lines: green and red
  const [points1, setPoints1] = useState([]);
  const [points2, setPoints2] = useState([]);
  const tRef = useRef(0);

  // Generate base points
  const basePoints = [0, 40, 80, 120, 160, 200, 240, 280, 320, 360, 400];

  useEffect(() => {
    let frame;
    function animate() {
      tRef.current += 0.008; // Slow animation
      // Animate two lines with sine/cosine and some phase offset
      const p1 = basePoints.map((x, i) => {
        const y = 40 + 20 * Math.sin(tRef.current + i * 0.5) + 10 * Math.sin(tRef.current * 0.5 + i);
        return `${x},${Math.round(y + 20)}`;
      });
      const p2 = basePoints.map((x, i) => {
        const y = 40 + 20 * Math.cos(tRef.current + i * 0.6) + 10 * Math.cos(tRef.current * 0.4 + i);
        return `${x},${Math.round(y)}`;
      });
      setPoints1(p1);
      setPoints2(p2);
      frame = requestAnimationFrame(animate);
    }
    animate();
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <svg
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ zIndex: 0, opacity }}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      preserveAspectRatio="none"
    >
      <polyline
        points={points1.join(' ')}
        stroke="green"
        strokeWidth="4"
        fill="none"
        strokeLinejoin="round"
      />
      <polyline
        points={points2.join(' ')}
        stroke="red"
        strokeWidth="4"
        fill="none"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// Helper to display intervals in label
const displayInterval = (interval) =>
  interval === "60"
    ? "1h"
    : interval === "240"
    ? "4h"
    : interval === "D"
    ? "1d"
    : `${interval}m`;

// Helper functions for consistent data parsing
const parseHedge = (hedgeValue) => {
  if (hedgeValue === true || hedgeValue === "true" || hedgeValue === 1 || hedgeValue === "1") return true;
  if (hedgeValue === false || hedgeValue === "false" || hedgeValue === 0 || hedgeValue === "0" || 
      hedgeValue === null || hedgeValue === undefined) return false;
  if (typeof hedgeValue === 'string') {
    const numValue = parseFloat(hedgeValue);
    return !isNaN(numValue) && numValue > 0;
  }
  return false;
};

const parseBoolean = (value) => {
  if (value === true || value === "true" || value === 1 || value === "1") return true;
  if (typeof value === 'string') {
    const numValue = parseFloat(value);
    return !isNaN(numValue) && numValue > 0;
  }
  return false;
};

const SESSION_CHECK_INTERVAL_MS = 30 * 1000; // check every 30 seconds

const App = () => {
  const [isLoggedIn, setLoggedIn] = useState(false);
  const [authChecking, setAuthChecking] = useState(true);
  const [showSessionWarning, setShowSessionWarning] = useState(false);

  const [superTrendData, setSuperTrendData] = useState([]);
  const [emaTrends, setEmaTrends] = useState(null);
  const [activeLossFlags, setActiveLossFlags] = useState(null);
  // Expose superTrendData for focused debugging (must be at top level, not inside render logic)
  useEffect(() => {
    window._superTrendData = superTrendData;
  }, [superTrendData]);
  const [metrics, setMetrics] = useState(null);
  const [selectedBox, setSelectedBox] = useState(null);
  const [tradeData, setTradeData] = useState([]);
  const [demoDataHint, setDemoDataHint] = useState(null); // when API returns _meta.demoData, show hint instead of demo rows
  const [apiBaseForBanner, setApiBaseForBanner] = useState(() => (typeof getApiBaseUrl === "function" ? getApiBaseUrl() : ""));
  const [apiUnreachable, setApiUnreachable] = useState(false);
  const [corsError, setCorsError] = useState(false);
  const [localServerDown, setLocalServerDown] = useState(false);
  const [clientData, setClientData] = useState([]);
  const [logData, setLogData] = useState([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [machines, setMachines] = useState([]);
  const [signalRadioMode, setSignalRadioMode] = useState(false);
  const [machineRadioMode, setMachineRadioMode] = useState(() => {
    const saved = localStorage.getItem("machineRadioMode");
    return saved ? JSON.parse(saved) : false;
  });
  const toMachineKey = useCallback((id) => (id === null || id === undefined ? "" : String(id)), []);
  const [includeMinClose, setIncludeMinClose] = useState(true);
  const [activeSubReport, setActiveSubReport] = useState("running");
  const [fontSizeLevel, setFontSizeLevel] = useState(() => {
    const saved = localStorage.getItem("fontSizeLevel");
    return saved ? parseInt(saved, 10) : 3; // default level 3
  });
  // Chart settings state
  const [chartSettings, setChartSettings] = useState(() => {
    // Try to load from localStorage for persistence if desired
    const saved = localStorage.getItem("chartSettings");
    return saved
      ? JSON.parse(saved)
      : {
          layout: 3,
          showRSI: true,
          showVolume: true,
        };
  });
  // Persist chartSettings to localStorage on change
  useEffect(() => {
    localStorage.setItem("chartSettings", JSON.stringify(chartSettings));
  }, [chartSettings]);

  // Responsive font scaling: update --app-font-scale on fontSizeLevel change
  useEffect(() => {
    const root = document.documentElement;
    const baseSize = 1; // default rem (1x)
    const adjustment = (fontSizeLevel - 8) * 0.25; // increase/decrease per level
    root.style.setProperty("--app-font-scale", `${baseSize + adjustment}`);
  }, [fontSizeLevel]);

  useEffect(() => {
    localStorage.setItem("fontSizeLevel", fontSizeLevel);
  }, [fontSizeLevel]);

  // Check session on mount
  useEffect(() => {
    checkSession().then((data) => {
      setLoggedIn(!!data);
      setAuthChecking(false);
    }).catch(() => {
      setLoggedIn(false);
      setAuthChecking(false);
    });
  }, []);

  // Periodically verify session is still valid
  useEffect(() => {
    if (!isLoggedIn) return;
    const id = setInterval(() => {
      checkSession().then((data) => {
        if (!data) {
          setLoggedIn(false);
          setShowSessionWarning(false);
        }
      });
    }, SESSION_CHECK_INTERVAL_MS);
    return () => clearInterval(id);
  }, [isLoggedIn]);

  // Global 401: any API call that returns 401 (e.g. session expired) → log out
  useEffect(() => {
    const onUnauthorized = () => {
      setLoggedIn(false);
      setShowSessionWarning(false);
    };
    window.addEventListener("lab-unauthorized", onUnauthorized);
    return () => window.removeEventListener("lab-unauthorized", onUnauthorized);
  }, []);

  // -------- Sound / New-Trade settings (non-invasive to filters) --------
  const SOUND_STORAGE_KEY = "soundSettings";
  const [isSoundOpen, setIsSoundOpen] = useState(false);
  const [soundSettings, setSoundSettings] = useState(() => {
    try {
      const saved = localStorage.getItem(SOUND_STORAGE_KEY);
      return saved
        ? JSON.parse(saved)
        : {
            enabled: false,
            volume: 0.7,
            mode: "tts",
            announceActions: { BUY: true, SELL: true },
            announceSignals: {},
            audioUrls: { BUY: "", SELL: "" },
            newTradeWindowHours: 4,
          };
    } catch {
      return {
        enabled: false,
        volume: 0.7,
        mode: "tts",
        announceActions: { BUY: true, SELL: true },
        announceSignals: {},
        audioUrls: { BUY: "", SELL: "" },
        newTradeWindowHours: 4,
      };
    }
  });
  useEffect(() => {
    localStorage.setItem(SOUND_STORAGE_KEY, JSON.stringify(soundSettings));
  }, [soundSettings]);


  const [layoutOption, setLayoutOption] = useState(() => {
    const saved = localStorage.getItem("layoutOption");
    return saved ? parseInt(saved, 10) : 3;
  }); // default 3 cards per row
  const [signalToggleAll, setSignalToggleAll] = useState(() => {
    const saved = localStorage.getItem("selectedSignals");
    if (saved) {
      const parsed = JSON.parse(saved);
      const allSelected = Object.values(parsed).every((val) => val === true);
      return allSelected ? false : true; // If all selected, button should show ❌ Uncheck
    }
    return true; // Default
  });
  const [machineToggleAll, setMachineToggleAll] = useState(() => {
    const saved = localStorage.getItem("machineToggleAll");
    return saved ? JSON.parse(saved) : true;
  });

  useEffect(() => {
    localStorage.setItem("machineRadioMode", machineRadioMode);
  }, [machineRadioMode]);

  useEffect(() => {
    localStorage.setItem("machineToggleAll", machineToggleAll);
  }, [machineToggleAll]);
  
  // ChartGrid state
  const [showChartGrid, setShowChartGrid] = useState(false);
  const [chartGridSymbols, setChartGridSymbols] = useState(['BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT']);
  
const [fromDate, setFromDate] = useState(() => {
  const saved = localStorage.getItem("fromDate");
  return saved ? moment(saved) : null;
});

const [toDate, setToDate] = useState(() => {
  const saved = localStorage.getItem("toDate");
  return saved ? moment(saved) : null;
});

useEffect(() => {
  if (fromDate) {
    localStorage.setItem("fromDate", fromDate.toISOString());
  } else {
    localStorage.removeItem("fromDate");
  }
}, [fromDate]);

useEffect(() => {
  if (toDate) {
    localStorage.setItem("toDate", toDate.toISOString());
  } else {
    localStorage.removeItem("toDate");
  }
}, [toDate]);

  const [selectedSignals, setSelectedSignals] = useState({
    "2POLE_IN5LOOP": true,
    "IMACD": true,
    "2POLE_Direct_Signal": true,
    "HIGHEST SWING HIGH": true,
    "LOWEST SWING LOW": true,
    "NORMAL SWING HIGH": true,
    "NORMAL SWING LOW": true,
    "ProGap": true,
    "CrossOver": true,
    "Spike": true,
    "Kicker": true,

  });
  const [intervalRadioMode, setIntervalRadioMode] = useState(false);
  const [actionRadioMode, setActionRadioMode] = useState(false);

const [selectedActions, setSelectedActions] = useState({
  BUY: true,
  SELL: true,
});
const [liveFilter, setLiveFilter] = useState(() => {
  const saved = localStorage.getItem("liveFilter");
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch {
      return { true: true, false: true };
    }
  }
  return { true: true, false: true }; // Both checked by default (show all)
});
useEffect(() => {
  localStorage.setItem("liveFilter", JSON.stringify(liveFilter));
}, [liveFilter]);
const [liveRadioMode, setLiveRadioMode] = useState(() => {
  const saved = localStorage.getItem("liveRadioMode");
  return saved === "true";
});
useEffect(() => {
  localStorage.setItem("liveRadioMode", liveRadioMode ? "true" : "false");
}, [liveRadioMode]);
const [filterVisible, setFilterVisible] = useState(() => {
  const saved = localStorage.getItem("filterVisible");
  if (saved === "false") return false;
  return true;
});

useEffect(() => {
  localStorage.setItem("filterVisible", filterVisible ? "true" : "false");
}, [filterVisible]);

// Sync selectedActions when actionRadioMode changes (radio-mode behavior)
useEffect(() => {
  if (actionRadioMode) {
    const selected = Object.keys(selectedActions).find((key) => selectedActions[key]);
    if (selected) {
      const updated = { BUY: false, SELL: false };
      updated[selected] = true;
      setSelectedActions(updated);
      localStorage.setItem("selectedActions", JSON.stringify(updated));
    }
  }
}, [actionRadioMode]);
const [selectedIntervals, setSelectedIntervals] = useState(() => {
  const saved = localStorage.getItem("selectedIntervals");
  return saved
    ? JSON.parse(saved)
    : { "1m": true, "3m": true, "5m": true, "15m": true, "30m": true, "1h": true, "2h": true, "4h": true };
});
  const [selectedMachines, setSelectedMachines] = useState({});
  const [dateKey, setDateKey] = useState(0);
  

  const refreshAllData = useCallback(async () => {
    // On GitHub Pages with no API configured, skip requests until api-config.json or build URL is set
    if (typeof window !== "undefined" && window.location?.hostname?.includes("github.io") && !getApiBaseUrl()) {
      setTradeData([]);
      setMachines([]);
      setLogData([]);
      setClientData([]);
      setSuperTrendData([]);
      setEmaTrends(null);
      setActiveLossFlags(null);
      setDemoDataHint(null);
      return;
    }
    try {
      setApiUnreachable(false);
      // Sync Binance open positions to DB before fetching trades (so fresh data shows on load/refresh)
      try {
        await apiFetch("/api/sync-open-positions").catch(() => {});
      } catch (_) {}
      const tradeRes = await apiFetch("/api/trades");
      if (tradeRes.status === 401) { setLoggedIn(false); return; }
      const tradeJson = tradeRes.ok ? await tradeRes.json() : { trades: [] };
      const trades = Array.isArray(tradeJson.trades) ? tradeJson.trades : [];
      console.log("[DEBUG] Trades received:", trades.length, "rows");
      setDemoDataHint(tradeJson._meta?.demoData ? tradeJson._meta.hint || null : null);

      const machinesRes = await apiFetch("/api/machines");
      const machinesJson = machinesRes.ok ? await machinesRes.json() : { machines: [] };
      const machinesList = Array.isArray(machinesJson.machines) ? machinesJson.machines : [];
      console.log("[DEBUG] Machines received:", machinesList.length, "machines");

      // Use base path so logs.json works on GitHub Pages (e.g. /lab_live/logs.json)
      const logsPath = `${(import.meta.env.BASE_URL || "/").replace(/\/?$/, "/")}logs.json`;
      const logRes = await fetch(logsPath).catch(() => ({ ok: false }));
      const logJson = logRes.ok ? await logRes.json() : { logs: [] };
      const logs = Array.isArray(logJson?.logs) ? logJson.logs : [];

      // Fetch SuperTrend data
      console.log("[API DEBUG] fetch /api/supertrend");
      const superTrendRes = await apiFetch("/api/supertrend");
      const superTrendJson = superTrendRes.ok ? await superTrendRes.json() : { supertrend: [] };
      setSuperTrendData(Array.isArray(superTrendJson.supertrend) ? superTrendJson.supertrend : []);

      // Fetch EMA trend data
      console.log("[API DEBUG] fetch /api/pairstatus");
      const emaRes = await apiFetch("/api/pairstatus");
      const emaJson = emaRes.ok ? await emaRes.json() : null;
      setEmaTrends(emaJson);

      // Fetch BUY/SELL live flags
      try {
        console.log("[API DEBUG] fetch /api/active-loss");
        const flagsRes = await apiFetch("/api/active-loss");
        const flagsJson = flagsRes.ok ? await flagsRes.json() : null;
        setActiveLossFlags(flagsJson || null);
      } catch {
        setActiveLossFlags(null);
      }

      // Build unified machine list (machines endpoint + trades machine ids)
      const tradeMachineIds = Array.from(
        new Set(trades.map(t => toMachineKey(t.machineid)).filter(Boolean))
      ).map(id => ({ machineid: id, active: true }));
      const unifiedMachines = [
        ...machinesList,
        ...tradeMachineIds.filter(tm => !machinesList.some(m => toMachineKey(m.machineid) === tm.machineid))
      ];

      setMachines(unifiedMachines);
      setTradeData(trades);
      setLogData(logs);
      setClientData(unifiedMachines);
      
      // Clear CORS error if we got data successfully
      if (corsError && trades.length > 0) {
        console.log("[DEBUG] ✅ CORS error cleared - data loaded successfully");
        setCorsError(false);
      }

      // Preserve user selections: keep previous values; new machines default to true
      // Always select ALL machines (ignore active status) so every machine’s trades show
      const allMachinesSelected = unifiedMachines.reduce((acc, machine) => {
        const key = toMachineKey(machine.machineid);
        if (key) acc[key] = true;
        return acc;
      }, {});
      setSelectedMachines(allMachinesSelected);
      localStorage.setItem("selectedMachines", JSON.stringify(allMachinesSelected));

      // Debug: log machine coverage
      const countsByMachine = trades.reduce((acc, t) => {
        const k = toMachineKey(t.machineid) || "unknown";
        acc[k] = (acc[k] || 0) + 1;
        return acc;
      }, {});
      console.log("[DEBUG] Machines from API:", machinesList.map(m => toMachineKey(m.machineid)));
      console.log("[DEBUG] Machines from trades:", tradeMachineIds);
      console.log("[DEBUG] Counts by machine from trades:", countsByMachine);
      console.log("[DEBUG] Selected machines:", allMachinesSelected);
    } catch (error) {
      setTradeData([]);
      setDemoDataHint(null);
      if (isLocalhostOrigin()) {
        setApiUnreachable(true);
        if (!getLocalhostUseCloudFallback()) setLocalServerDown(true);
      } else if (typeof window !== "undefined" && window.location?.hostname?.includes("github.io")) {
        const currentApiBase = getApiBaseUrl();
        console.log("[DEBUG] GitHub Pages error - current API base:", currentApiBase);
        setApiUnreachable(true);
        if (typeof loadRuntimeApiConfig === "function") {
          loadRuntimeApiConfig().then(() => setTimeout(() => refreshAllData(), 2000));
        }
      }
    }
  }, [toMachineKey]);

  useEffect(() => {
    refreshAllData();
  }, [refreshAllData]);

  // When api-config.json loads (fixed API URL), refresh data
  useEffect(() => {
    const onConfigLoaded = () => {
      setApiBaseForBanner(getApiBaseUrl());
      refreshAllData();
    };
    window.addEventListener("api-config-loaded", onConfigLoaded);
    return () => window.removeEventListener("api-config-loaded", onConfigLoaded);
  }, [refreshAllData]);

  // Debug: log machine coverage and trade counts (raw vs filtered)
const filteredTradeData = useMemo(() => {
  if (!Array.isArray(tradeData)) return [];
  const isSelected = (map, key) => {
    return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : true; // default allow unknown keys
  };
 
  return tradeData.filter(trade => {

    if (!includeMinClose && trade.min_close === "Min_close") return false;
    const isSignalSelected = isSelected(selectedSignals, trade.signalfrom);
    const isMachineSelected = isSelected(selectedMachines, toMachineKey(trade.machineid));
    const isIntervalSelected = isSelected(selectedIntervals, trade.interval);
    const isActionSelected = isSelected(selectedActions, trade.action);
    // Filter by exist_in_exchange: check if trade's value matches selected filter
    const v = trade.exist_in_exchange ?? trade.Exist_in_exchange;
    const isLive = v === true || v === "true" || v === 1 || v === "1";
    if (liveFilter.true && liveFilter.false) {
      // Both selected: show all
    } else if (liveFilter.true && !isLive) {
      return false; // Only true selected, but trade is false
    } else if (liveFilter.false && isLive) {
      return false; // Only false selected, but trade is true
    } else if (!liveFilter.true && !liveFilter.false) {
      return false; // Neither selected: show nothing
    }

    // ✅ Handle missing or malformed Candle time
    if (!trade.candel_time) return false;

    const tradeTime = moment(trade.candel_time); // ⏳ Parse to moment

    // ✅ Check if within selected date & time range
    const isDateInRange = (!fromDate || tradeTime.isSameOrAfter(fromDate)) &&
                          (!toDate || tradeTime.isSameOrBefore(toDate));

    return isSignalSelected && isMachineSelected && isIntervalSelected && isActionSelected && isDateInRange;
  });
  // console.log('[App.jsx] filteredTradeData:', filteredTradeData);
}, [tradeData, selectedSignals, selectedMachines, selectedIntervals, selectedActions, fromDate, toDate, includeMinClose, fontSizeLevel, liveFilter]);

// Debug: log machine coverage and trade counts (raw vs filtered)
useEffect(() => {
  if (!machines.length && !tradeData.length) return;
  const uniqueIntervals = Array.from(new Set(tradeData.map(t => t.interval)));
  const uniqueSignals = Array.from(new Set(tradeData.map(t => t.signalfrom)));
  const uniqueActions = Array.from(new Set(tradeData.map(t => t.action)));
  const countsRaw = tradeData.reduce((acc, t) => {
    const k = toMachineKey(t.machineid) || "unknown";
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
  const countsFiltered = filteredTradeData.reduce((acc, t) => {
    const k = toMachineKey(t.machineid) || "unknown";
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
  console.log("[DEBUG][Machines] API machines:", machines.map(m => toMachineKey(m.machineid)));
  console.log("[DEBUG][Machines] Selected map:", selectedMachines);
  console.log("[DEBUG][Trades] Raw counts by machine:", countsRaw);
  console.log("[DEBUG][Trades] Filtered counts by machine:", countsFiltered);
  console.log("[DEBUG][Trades] Unique intervals:", uniqueIntervals);
  console.log("[DEBUG][Trades] Unique signals:", uniqueSignals);
  console.log("[DEBUG][Trades] Unique actions:", uniqueActions);
}, [machines, tradeData, filteredTradeData, selectedMachines, toMachineKey]);

const getFilteredForTitle = useMemo(() => {
  const memo = {};


  (filteredTradeData || []).forEach((trade) => {
    const pushTo = (key) => {
      if (!memo[key]) memo[key] = [];
      memo[key].push(trade);  // ✅ Only push raw trade here
    };

    pushTo("Total_Trades");

    if (trade.type === "close") pushTo("Profit_+_Loss_=_Closed_Profit $");
    if (trade.type === "running" || trade.type === "hedge_hold") pushTo("Profit_+_Loss_=_Running_Profit $");
    if (["assign", "running", "close", "hedge_hold"].includes(trade.type)) pushTo("Assign_/_Running_/_Closed Count");

    if (trade.action === "BUY" && (trade.type === "running" || trade.type === "hedge_hold")) {
      pushTo("Running_/_Total_Buy");
    }

    if (trade.action === "SELL" && (trade.type === "running" || trade.type === "hedge_hold")) {
      pushTo("Running_/_Total_Sell");
    }

    const isHedge = parseHedge(trade.hedge);
    const isHedge11 = parseBoolean(trade.hedge_1_1_bool);
    const isCommisionJourney = parseBoolean(trade.commision_journey);
    const isProfitJourney = parseBoolean(trade.profit_journey);
    
    if (isCommisionJourney && trade.pl_after_comm > 0 && !isProfitJourney && (trade.type === "running" || trade.type === "hedge_hold")) pushTo("Comission_Point_Crossed");
    if (isProfitJourney && trade.pl_after_comm > 0 && (trade.type === "running" || trade.type === "hedge_hold")) pushTo("Profit_Journey_Crossed");
    if (trade.pl_after_comm < 0 && (trade.type === "running" || trade.type === "hedge_hold")) pushTo("Below_Commision_Point");

    if (trade.type === "close" && isCommisionJourney && !isProfitJourney) pushTo("Closed_After_Comission_Point");
    if (trade.type === "close" && trade.pl_after_comm < 0) pushTo("Close_in_Loss");
    if (isHedge) pushTo("Total_Hedge");
    if (isHedge && (trade.type === "running" || trade.type === "hedge_hold")) pushTo("Hedge_Running_pl");
    if (isHedge && trade.type === "close") pushTo("Hedge_Closed_pl");

    if (trade.type === "close" && trade.pl_after_comm > 0) pushTo("Close_in_Profit");
    if (trade.type === "close" && isProfitJourney) pushTo("Close_After_Profit_Journey");
    if (trade.type === "close" && isCommisionJourney && trade.pl_after_comm < 0) pushTo("Close_Curve_in_Loss");

    if (trade.type === "close" && trade.min_close === "Min_close") {
      if (trade.pl_after_comm > 0) pushTo("Min_Close_Profit");
      if (trade.pl_after_comm < 0) pushTo("Min_Close_Loss");
    }

    // Closed Stats
    if (trade.type === "close") {
      pushTo("Total_Closed_Stats");
      pushTo("Closed_Count_Stats");
      
      if (!isHedge) pushTo("Direct_Closed_Stats");
    }
    
    // Hedge Closed Stats - use hedge_close type
    if (trade.type === "hedge_close") {
      pushTo("Hedge_Closed_Stats");
    }
    
    // Running Stats
    if (trade.type === "running" || trade.type === "hedge_hold") {
      pushTo("Total_Running_Stats");
      // Treat type=hedge_hold as hedge even if hedge flag is unset
      const isHedgeEffective = isHedge || trade.type === "hedge_hold";
      if (!isHedgeEffective) {
        pushTo("Direct_Running_Stats");
      }
      if (isHedgeEffective && !isHedge11) {
        pushTo("Hedge_Running_Stats");
      }
    }
    
    // Hedge on Hold (trades that are hedge and running)
    if ((isHedge || trade.type === "hedge_hold") && isHedge11 && (trade.type === "running" || trade.type === "hedge_hold")) pushTo("Hedge_on_Hold");
    
    // Total Stats (all trades)
    pushTo("Total_Stats");
    
    // Assigned trades: include new assigns and backend-closed assigns
    if (trade.type === "assign" || trade.type === "back_close") pushTo("Assigned_New");
    



    if (isHedge) pushTo("Hedge_Stats");

    // --- ADD: Buy_Sell_Stats logic
    if (["BUY", "SELL"].includes(trade.action)) pushTo("Buy_Sell_Stats");

    // --- ADD: Journey_Stats logic (fix missing)
    if ((trade.type === "running" || trade.type === "hedge_hold") && trade.pl_after_comm > 0 && isProfitJourney) pushTo("Journey_Stats_Running");
    if ((trade.type === "running" || trade.type === "hedge_hold") && trade.pl_after_comm > 0 && isCommisionJourney && !isProfitJourney) pushTo("Journey_Stats_Running");
    if ((trade.type === "running" || trade.type === "hedge_hold") && trade.pl_after_comm < 0) pushTo("Journey_Stats_Running");
  });

  
  return memo;
}, [filteredTradeData]);

  // Signals list available in current filtered data (for settings UI)
  const availableSignals = useMemo(() => {
    const set = new Set((Array.isArray(filteredTradeData) ? filteredTradeData : []).map(t => t.signalfrom).filter(Boolean));
    return Array.from(set);
  }, [filteredTradeData]);

  // Build a stable key for a trade (for sound dedupe)
  const tradeKey = (t) => {
    const uid = t.unique_id || t.Unique_ID || t.uid;
    if (uid) return `uid:${String(uid)}`;
    const tm = t.candel_time || t.candle_time || t.timestamp || t.created_at;
    const pair = t.pair || t.Pair || t.symbol || "";
    const action = t.action || t.Action || "";
    return `ts:${String(tm)}|${pair}|${action}`;
  };

  // Subset: new direct running trades within N hours (based on candel_time and current filters)
  const newDirectRunning = useMemo(() => {
    const hours = Number(soundSettings?.newTradeWindowHours || 4);
    // Window is evaluated in IST
    const nowIst = moment.utc().utcOffset(330);
    return (filteredTradeData || []).filter(t => {
      const isHedgeEffective = parseHedge(t.hedge) || t.type === "hedge_hold";
      // Only direct pure running trades (exclude hedge_hold regardless of flag)
      const isDirectRunning = (t.type === "running") && !isHedgeEffective;
      if (!isDirectRunning) return false;
      // Prefer Fetcher (UTC) time, then fallbacks
      const ts =
        t.fetcher_trade_time ||
        t.Fetcher_Trade_time ||
        t.fetch_time ||
        t.candel_time ||
        t.candle_time ||
        t.timestamp ||
        t.created_at;
      if (!ts) return false;
      // Convert UTC -> IST for window comparison
      const mIst = moment.utc(ts).utcOffset(330);
      if (!mIst.isValid()) return false;
      return nowIst.diff(mIst, "hours", true) <= hours;
    });
  }, [filteredTradeData, soundSettings]);

  // Persist announced keys to avoid repeat after refresh
  const ANNOUNCED_STORAGE_KEY = "announcedTradeKeysV1";
  const announcedMapRef = useRef(new Map()); // key -> timestamp
  useEffect(() => {
    try {
      const raw = localStorage.getItem(ANNOUNCED_STORAGE_KEY);
      if (raw) {
        const obj = JSON.parse(raw);
        const now = Date.now();
        const sevenDays = 7 * 24 * 3600 * 1000;
        Object.entries(obj || {}).forEach(([k, ts]) => {
          if (typeof ts === "number" && now - ts < sevenDays) {
            announcedMapRef.current.set(k, ts);
          }
        });
      }
    } catch {}
  }, []);
  const persistAnnounced = () => {
    const entries = Array.from(announcedMapRef.current.entries()).sort((a,b)=>b[1]-a[1]).slice(0,5000);
    try { localStorage.setItem(ANNOUNCED_STORAGE_KEY, JSON.stringify(Object.fromEntries(entries))); } catch {}
  };

  // Play one notification honoring settings
  const playNotification = (t) => {
    if (!soundSettings?.enabled) return;
    const action = String(t.action || "").toUpperCase();
    const signal = String(t.signalfrom || "");
    if (soundSettings.announceActions && soundSettings.announceActions[action] === false) return;
    if (soundSettings.announceSignals && Object.keys(soundSettings.announceSignals).length && soundSettings.announceSignals[signal] === false) return;
    const volume = Math.max(0, Math.min(1, Number(soundSettings.volume || 0.7)));
    if (soundSettings.mode === "audio") {
      const url = soundSettings.audioUrls?.[action];
      if (url) {
        try { const audio = new Audio(url); audio.volume = volume; audio.play().catch(()=>{}); } catch {}
        return;
      }
    }
    try {
      const phrase = `${action === "BUY" ? "Buy" : action === "SELL" ? "Sell" : action} from ${signal || "signal"}`;
      const u = new SpeechSynthesisUtterance(phrase);
      u.volume = volume;
      window.speechSynthesis.speak(u);
    } catch {}
  };

  // Sound only for newly seen items in the subset; persist announced keys
  const seenSubsetRef = useRef(new Set());
  useEffect(() => {
    const subset = Array.isArray(newDirectRunning) ? newDirectRunning : [];
    const subsetKeys = new Set(subset.map(tradeKey));
    const newOnes = subset.filter(t => !seenSubsetRef.current.has(tradeKey(t)));
    seenSubsetRef.current = subsetKeys;
    const toAnnounce = newOnes.filter(t => !announcedMapRef.current.has(tradeKey(t)));
    if (!toAnnounce.length) return;
    toAnnounce.forEach(t => {
      playNotification(t);
      announcedMapRef.current.set(tradeKey(t), Date.now());
    });
    persistAnnounced();
  }, [newDirectRunning, soundSettings]);

useEffect(() => {
  // 🔹 Total Investment Calculation
  const totalInvestment = filteredTradeData.reduce((sum, trade) => sum + (trade.investment || 0), 0);
  let investmentAvailable = 50000 - totalInvestment;
  investmentAvailable = investmentAvailable < 0 ? 0 : investmentAvailable; // ✅ Prevent negative values

  const closePlus = filteredTradeData
    .filter(trade => trade.pl_after_comm > 0 && trade.type === "close" ) // ✅ Correct field reference
    .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  const closeMinus = filteredTradeData
    .filter(trade => trade.pl_after_comm < 0 && trade.type === "close"  ) // ✅ Correct field reference
    .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  const runningPlusFiltered = filteredTradeData
    .filter(trade => {
      const isHedgeEffective = parseHedge(trade.hedge) || trade.type === "hedge_hold";
      return trade.pl_after_comm > 0 && trade.type === "running" && !isHedgeEffective;
    });
  const runningMinusFiltered = filteredTradeData
    .filter(trade => {
      const isHedgeEffective = parseHedge(trade.hedge) || trade.type === "hedge_hold";
      return trade.pl_after_comm < 0 && trade.type === "running" && !isHedgeEffective;
    });

  const runningPlus = runningPlusFiltered.reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  const runningMinus = runningMinusFiltered.reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  const closedProfit = filteredTradeData
      .filter(trade => trade.type === "close")
      .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  const runningProfit = filteredTradeData
    .filter(trade => {
      const isHedgeEffective = parseHedge(trade.hedge) || trade.type === "hedge_hold";
      return trade.type === "running" && !isHedgeEffective;
    })
    .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);

  const buyRunningDirect = filteredTradeData.filter(t => {
    const isHedgeEffective = parseHedge(t.hedge) || t.type === "hedge_hold";
    return t.action === "BUY" && t.type === "running" && !isHedgeEffective;
  }).length;
  const buyRunningHedge = filteredTradeData.filter(t => {
    const isHedgeEffective = parseHedge(t.hedge) || t.type === "hedge_hold";
    return t.action === "BUY" && (t.type === "running" || t.type === "hedge_hold") && isHedgeEffective;
  }).length;
  const buyRunningCloseD = filteredTradeData.filter(t => t.action === "BUY" && t.type === "close").length ;
  const buyRunningCloseH = filteredTradeData.filter(t => t.action === "BUY" && t.type === "hedge_close").length ;
  const buyRunningClose = buyRunningCloseD + buyRunningCloseH;


  const buyTotal = filteredTradeData.filter(t => t.action === "BUY").length;
  const sellRunningDirect = filteredTradeData.filter(t => {
    const isHedgeEffective = parseHedge(t.hedge) || t.type === "hedge_hold";
    return t.action === "SELL" && t.type === "running" && !isHedgeEffective;
  }).length;
  const sellRunningHedge = filteredTradeData.filter(t => {
    const isHedgeEffective = parseHedge(t.hedge) || t.type === "hedge_hold";
    return t.action === "SELL" && (t.type === "running" || t.type === "hedge_hold") && isHedgeEffective;
  }).length;
  const sellRunningCloseD = filteredTradeData.filter(t => t.action === "SELL" && t.type === "close" ).length;
  const sellRunningCloseH = filteredTradeData.filter(t => t.action === "SELL" && t.type === "hedge_close").length;
  const sellRunningClose = sellRunningCloseD + sellRunningCloseH;





  const sellTotal = filteredTradeData.filter(t => t.action === "SELL").length;

  const hedgePlusRunning = filteredTradeData
  .filter(trade => {
    const hedgeValue = trade.hedge || trade.Hedge || trade.hedge_bool || trade.Hedge_bool;
    const hedge11Value = trade.hedge_1_1_bool || trade.Hedge_1_1_bool || trade.hedge_1_1 || trade.Hedge_1_1;
    const plValue = trade.pl_after_comm || trade.Pl_after_comm;
    
    const isHedge = parseHedge(hedgeValue);
    const isHedge11 = parseBoolean(hedge11Value);
    return plValue > 0 && isHedge && isHedge11;
  })
  .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm || trade.Pl_after_comm) || 0), 0);
  const hedgeMinusRunning = filteredTradeData
    .filter(trade => {
      const hedgeValue = trade.hedge || trade.Hedge || trade.hedge_bool || trade.Hedge_bool;
      const hedge11Value = trade.hedge_1_1_bool || trade.Hedge_1_1_bool || trade.hedge_1_1 || trade.Hedge_1_1;
      const plValue = trade.pl_after_comm || trade.Pl_after_comm;
      
      const isHedge = parseHedge(hedgeValue);
      const isHedge11 = parseBoolean(hedge11Value);
      return plValue < 0 && isHedge && isHedge11;
    })
    .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm || trade.Pl_after_comm) || 0), 0);   
  const hedgeRunningProfit = filteredTradeData
      .filter(trade => {
        const hedgeValue = trade.hedge || trade.Hedge || trade.hedge_bool || trade.Hedge_bool;
        const hedge11Value = trade.hedge_1_1_bool || trade.Hedge_1_1_bool || trade.hedge_1_1 || trade.Hedge_1_1;
        const typeValue = trade.type || trade.Type || "";
        
        const isHedge = parseHedge(hedgeValue);
        const isHedge11 = parseBoolean(hedge11Value);
        
        // Use same logic as count - not closed trades
        const isNotClosed = !typeValue.toLowerCase().includes("close") && 
                           !typeValue.toLowerCase().includes("assign");
        
        return isHedge && isHedge11 && isNotClosed;
      })
      .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm || trade.Pl_after_comm) || 0), 0);

  const hedgeActiveRunningPlus = filteredTradeData
  .filter(trade => {
    const isHedgeEffective = parseHedge(trade.hedge) || trade.type === "hedge_hold";
    const isHedge11 = parseBoolean(trade.hedge_1_1_bool);
    return isHedgeEffective && !isHedge11 && trade.pl_after_comm > 0 && (trade.type === "running" || trade.type === "hedge_hold");
  })
  .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  const hedgeActiveRunningMinus = filteredTradeData 
  .filter(trade => {
    const isHedgeEffective = parseHedge(trade.hedge) || trade.type === "hedge_hold";
    const isHedge11 = parseBoolean(trade.hedge_1_1_bool);
    return isHedgeEffective && !isHedge11 && trade.pl_after_comm < 0 && (trade.type === "running" || trade.type === "hedge_hold");
  })
  .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  const hedgeActiveRunningTotal = filteredTradeData
  .filter(trade => {
    const isHedgeEffective = parseHedge(trade.hedge) || trade.type === "hedge_hold";
    const isHedge11 = parseBoolean(trade.hedge_1_1_bool);
    return isHedgeEffective && !isHedge11 && (trade.type === "running" || trade.type === "hedge_hold");
  })
  .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);

  const hedgeClosedPlus = filteredTradeData
  .filter(trade => trade.type === "hedge_close" && trade.pl_after_comm > 0)
  .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  const hedgeClosedMinus = filteredTradeData
  .filter(trade => trade.type === "hedge_close" && trade.pl_after_comm < 0)
  .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  const hedgeClosedTotal = filteredTradeData
  .filter(trade => trade.type === "hedge_close"  )
  .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0);
  
  const minCloseProfitVlaue = filteredTradeData
    .filter(trade => trade.min_close === "Min_close"  &&  trade.type === "close" && trade.pl_after_comm > 0)
    .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0).toFixed(2)
  
  const minCloseLossVlaue = filteredTradeData
    .filter(trade => trade.min_close === "Min_close"  &&  trade.type === "close" && trade.pl_after_comm < 0)
    .reduce((sum, trade) => sum + (parseFloat(trade.pl_after_comm) || 0), 0).toFixed(2)

   // console.log("🔍 Filtered Trade Data:", filteredTradeData);  


  // 🔹 Format dates for comparison
  // const today = new Date().toISOString().split("T")[0];
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  // const yesterdayDate = yesterday.toISOString().split("T")[0];

  setMetrics(prevMetrics => ({
    ...prevMetrics,
Total_Closed_Stats: (
          <>
{/* className={`relative px-[3px] text-yellow-300 font-semibold font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }} */}

              <span title="Closed Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>Total Closed Trades &nbsp;</span>
              <span title="Closed Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇&nbsp;</span>
             
             &nbsp;
               <span title="Closed Count" className={`relative px-[3px] text-yellow-300 font-semibold  font-semibold`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {filteredTradeData.filter(trade => trade.type === "close" || trade.type === "hedge_close").length}
              </span>
             
              <div style={{ height: '14px' }} />
              <span title="Closed Profit (Hedge + Direct) " className={`text-green-300 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {(closePlus + hedgeClosedPlus).toFixed(2)}
              </span>
              &nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>+ </span>&nbsp;
              <span title="Closed Loss (Hedge + Direct)" className={`text-red-400 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {(closeMinus  +  hedgeClosedMinus).toFixed(2)}
              </span>
              &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=</span>&nbsp;&nbsp;
              <span
                className={`${closedProfit >= 0 ? "text-green-300" : "text-red-400"} text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}
                title="Closed Total (Hedge + Direct)"
              >
                {((closePlus + hedgeClosedPlus)+(closeMinus + hedgeClosedMinus)).toFixed(2)}
              </span>
              </>),
Direct_Closed_Stats: (
          <>

               <span title="Closed Count (Only Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>Direct Closed Trades&nbsp;</span>
              <span title="Closed Count (Only Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇&nbsp;</span>
                &nbsp;
             
              <span title="Closed Count" className={`relative px-[3px] text-yellow-300 font-semibold  font-semibold`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {filteredTradeData.filter(trade => trade.type === "close" ).length}
              </span>
             
              <div style={{ height: '14px' }} />

              <span title="Closed Profit (Only Direct) " className={`text-green-300 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {(closePlus).toFixed(2)}
              </span>
              &nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>+ </span>&nbsp;
              <span title="Closed Loss (Only Direct)" className={`text-red-400 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {(closeMinus).toFixed(2)}
              </span>
              &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=</span>&nbsp;&nbsp;
              <span
                className={`${(closePlus + closeMinus ) >= 0 ? "text-green-300" : "text-red-400"} text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}
                title="Closed Total (Only Direct)"
              >
                {(closePlus + closeMinus ).toFixed(2)}
              </span>
              </>),
Hedge_Closed_Stats: (
            <>

               <span title="Total Trades Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold font-semibold`} style={{ fontSize: `${26 + (fontSizeLevel - 8) * 5}px` }}>Hedge Closed  &nbsp;</span>
              <span title="Total Trades Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇&nbsp;</span>
            &nbsp;
             
              <span
                className={`relative px-[3px] text-yellow-300 font-semibold  font-semibold`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}
                title="Closed Hedge Count"
              >
                {filteredTradeData.filter(trade => {
                // Count all explicit hedge_close trades (hedge flag may be unset)
                return trade.type === "hedge_close";
              }).length}
              </span>
             
              <div style={{ height: '14px' }} />
              <span className={`text-green-300 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }} title="Closed Hedge Profit +">{hedgeClosedPlus.toFixed(2)}</span>
              &nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>+ </span>&nbsp;
              <span className={`text-red-400 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }} title="Closed Hedge Profit -">{hedgeClosedMinus.toFixed(2)}</span>
              &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=</span>&nbsp;&nbsp;
              <span className={`${hedgeClosedTotal >= 0 ? "text-green-300" : "text-red-400"} text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }} title="Closed Hedge Profit Total">{hedgeClosedTotal.toFixed(2)}</span>
            </>
          ),
Total_Running_Stats: (
          <>


             <span title="Running Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>Total Running Trades&nbsp;</span>
             <span title="Running Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇</span>
             &nbsp;
           
            <span title="Running Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold  font-semibold`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {filteredTradeData.filter(trade => {
                const isHedge11 = parseBoolean(trade.hedge_1_1_bool);
                return (trade.type === "running" || trade.type === "hedge_hold") && !isHedge11;
              }).length}
              </span>
              
           
           <div style={{ height: '14px' }} />
              &nbsp;
              <span title="Running Profit (Hedge + Direct)" className={`text-green-300 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {(runningPlus+hedgeActiveRunningPlus).toFixed(2)}
              </span>
              &nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>+ </span>&nbsp;
              <span title="Running Loss (Hedge + Direct)" className={`text-red-400 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {(runningMinus + hedgeActiveRunningMinus).toFixed(2)}
              </span>
              &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=</span>&nbsp;&nbsp;
              <span
                className={`${(runningProfit + hedgeActiveRunningTotal) >= 0 ? "text-green-300" : "text-red-400"} text-[30px]`}style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}
                title="Running Total (Hedge + Direct)"
              >
                {((runningProfit + hedgeActiveRunningTotal)).toFixed(2)}
              </span>
               </>),
 Direct_Running_Stats: (
          <>
            
            
             <span title="Running Count (only Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>Direct Running Trades&nbsp;</span>
             <span title="Running Count (only Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇</span>
            &nbsp;
            <span title="Running Count (only Direct)" className={`relative px-[3px] text-yellow-300 font-semibold  font-semibold`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {filteredTradeData.filter(trade => {
                  const isHedgeEffective = parseHedge(trade.hedge) || trade.type === "hedge_hold";
                  return trade.type === "running" && !isHedgeEffective;
                }).length}
              </span>
              
           <div style={{ height: '14px' }} />
              &nbsp;
              <span title="Running Profit (only Direct)" className={`text-green-300 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {runningPlus.toFixed(2)}
              </span>
              &nbsp;<span style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>+ </span>&nbsp;
              <span title="Running Loss (only Direct)" className={`text-red-400 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {runningMinus.toFixed(2)}
              </span>
              &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=</span>&nbsp;&nbsp;
              <span
                className={`${runningProfit >= 0 ? "text-green-300" : "text-red-400"} text-[30px]`}style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}
                title="Running Total (only Direct)"
              >
                {runningProfit.toFixed(2)}
              </span>
               </>),
 Hedge_Running_Stats: (
            <>

              <span title="Total Trades Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold  font-semibold`} style={{ fontSize: `${26 + (fontSizeLevel - 8) * 5}px` }}>Hedge Running&nbsp;</span>
              <span title="Total Trades Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇&nbsp;</span>
              &nbsp;
              
              <span
                className={`relative px-[3px] text-yellow-300 font-semibold  font-semibold`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}
                title="Running Hedge Count"
              >
                {filteredTradeData.filter(trade => {
                  const isHedgeEffective = parseHedge(trade.hedge) || trade.type === "hedge_hold";
                  const isHedge11 = parseBoolean(trade.hedge_1_1_bool);
                  return !isHedge11 && isHedgeEffective && (trade.type === "running" || trade.type === "hedge_hold");
                }).length}
              </span>

              <div style={{ height: '14px' }} />
              <span className={`text-green-300 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }} title="Running Hedge in Profit">{hedgeActiveRunningPlus.toFixed(2)}</span>
              &nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>+ </span>&nbsp;
              <span className={`text-red-400 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }} title="Running Hedge in Loss ">{hedgeActiveRunningMinus.toFixed(2)}</span>
              &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=</span>&nbsp;&nbsp;
              <span className={`${hedgeActiveRunningTotal >= 0 ? "text-green-300" : "text-red-400"} text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }} title="Running Hedge Total">{hedgeActiveRunningTotal.toFixed(2)}</span>
              </>
          ),


Total_Stats: (
          <>
               

              
              <span title="Total Trades Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>All Total Trades&nbsp;</span>
              <span title="Total Trades Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇&nbsp;</span>
             &nbsp;
              <span title="Total Trades Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold  font-semibold`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {filteredTradeData.length}
              </span>
              <div style={{ height: '14px' }} />
              <span title="Total Profit (Hedge + Direct) " className={`text-green-300 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {(runningPlus + hedgeActiveRunningPlus + hedgePlusRunning + hedgeClosedPlus + closePlus ).toFixed(2)}
              </span>
              &nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>+ </span>&nbsp;
              <span title="Total Loss (Hedge + Direct)" className={`text-red-400 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>
                {(runningMinus + hedgeClosedMinus + hedgeMinusRunning + closeMinus + hedgeActiveRunningMinus).toFixed(2)}
              </span>
              &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=</span>&nbsp;&nbsp;
              <span
                className={`${((runningPlus + hedgeActiveRunningPlus + hedgeClosedPlus + hedgePlusRunning + closePlus )+((runningMinus + hedgeClosedMinus + hedgeMinusRunning + closeMinus + hedgeActiveRunningMinus))).toFixed(2) >= 0 ? "text-green-300" : "text-red-400"} text-[35px]`}style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}
                title="Total (Hedge + Direct)"
              >
                {((runningPlus + hedgeActiveRunningPlus + hedgeClosedPlus + hedgePlusRunning + closePlus )+((runningMinus + hedgeClosedMinus + hedgeMinusRunning + closeMinus + hedgeActiveRunningMinus))).toFixed(2)}
              </span>
            </>
          ),
 Buy_Sell_Stats: (
            <>
              <div style={{ height: '6px' }} />

              <span className={`relative px-[3px] text-yellow-300 font-semibold`} style={{ fontSize: `${28 + (fontSizeLevel - 8) * 5}px` }}>Buy</span>
              <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80`} style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}> Direct-</span>
              <span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{buyRunningDirect}</span>
              <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80`} style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>, Hedge-</span>
              <span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{buyRunningHedge}</span>
                <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80`} style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>, Close-</span>
              <span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{buyRunningClose}</span>
              &nbsp;&nbsp;<span style={{ fontSize: `${20 + (fontSizeLevel - 8) * 5}px` }}>out of</span>&nbsp;
              <span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{buyTotal}</span>
              <div style={{ height: '10px' }} />
              <span className={`relative px-[3px] text-yellow-300 font-semibold`} style={{ fontSize: `${28 + (fontSizeLevel - 8) * 5}px` }}>Sell</span>
              <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80 `} style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}> Direct-</span>
              <span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{sellRunningDirect}</span>
              <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80 `} style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>, Hedge-</span>
               <span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{sellRunningHedge}</span>
                <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80`} style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>, Close-</span>
              <span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{sellRunningClose}</span>
              &nbsp;&nbsp;<span style={{ fontSize: `${20 + (fontSizeLevel - 8) * 5}px` }}>out of</span>&nbsp;
              <span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{sellTotal}</span>
              <br />
            </>
          ),
  Hedge_on_Hold: (
            <>

              
              <span title="Total Trades Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-200 font-semibold  font-semibold`} style={{ fontSize: `${26 + (fontSizeLevel - 8) * 5}px` }}>Hedge on hold  1-1 &nbsp;</span>
              <span title="Total Trades Count (Hedge + Direct)" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇&nbsp;</span>
              &nbsp;
              <span
                className={`relative px-[3px] text-yellow-300 font-semibold  font-semibold`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}
                title="Hedge 1-1 Count"
              >
                {(() => {
                  const hedgeOnHoldTrades = filteredTradeData.filter(trade => {
                    // Debug: check various possible field names for hedge
                    const hedgeValue = trade.hedge || trade.Hedge || trade.hedge_bool || trade.Hedge_bool || trade.hedgebool || trade.HedgeBool;
                    const hedge11Value = trade.hedge_1_1_bool || trade.Hedge_1_1_bool || trade.hedge_1_1 || trade.Hedge_1_1 || trade.hedge11bool || trade.Hedge11Bool;
                    
                    const isHedge = parseHedge(hedgeValue);
                    const isHedge11 = parseBoolean(hedge11Value);
                    const typeValue = trade.type || trade.Type || "";
                    
                    // Check for running trades - be more flexible with type matching
                    const isRunning = typeValue === "running" || 
                                     typeValue === "Running" || 
                                     typeValue === "hedge_hold" ||
                                     typeValue.toLowerCase().includes("running") ||
                                     (!typeValue || typeValue === ""); // Include trades with no type as potentially running
                    
                    // Debug logging (only for first few trades to avoid spam)
                    if (filteredTradeData.indexOf(trade) < 3) {
                      console.log("🔍 Hedge Debug - Trade:", trade.unique_id, {
                        hedgeValue,
                        hedge11Value,
                        isHedge,
                        isHedge11,
                        isRunning,
                        typeValue,
                        originalType: trade.type,
                        originalTypeCapital: trade.Type
                      });
                    }
                    
                    // For hedge on hold, we want trades that are hedge=true, hedge_1_1=true
                    // and are NOT closed (so running or no type specified)
                    const isNotClosed = !typeValue.toLowerCase().includes("close") && 
                                       !typeValue.toLowerCase().includes("assign");
                    
                    return isHedge && isHedge11 && isNotClosed;
                  });
                  
                  console.log("🔍 Hedge on Hold Count:", hedgeOnHoldTrades.length);
                  return hedgeOnHoldTrades.length;
                })()}
              </span>
              <div style={{ height: '14px' }} />
              <span className={`text-green-300 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }} title="Hedge 1-1 Profit">{hedgePlusRunning.toFixed(2)}</span>
              &nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>+ </span>&nbsp;
              <span className={`text-red-400 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }} title="Hedge 1-1 Loss">{hedgeMinusRunning.toFixed(2)}</span>
              &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=</span>&nbsp;&nbsp;
              <span className={`${hedgeRunningProfit >= 0 ? "text-green-300" : "text-red-400"} text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}title="Hedge 1-1 Total">{hedgeRunningProfit.toFixed(2)}</span>
              </>
          ),

// Closed_Count_Stats: (
//             <>
//             <span title="Closed Trades Count" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>Closed Trades Count&nbsp;</span>
//               <span title="Closed Trade Count" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇&nbsp;</span>
//                             <div style={{ height: '14px' }} />

//               <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80 font-semibold`} style={{ fontSize: `${19 + (fontSizeLevel - 8) * 5}px` }}>After&nbsp;&nbsp;&nbsp;PJ -&nbsp;</span><span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }} >{filteredTradeData.filter(trade => trade.Profit_journey === true && trade.Type === "close").length}</span>
           
//               <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80 font-semibold`} style={{ fontSize: `${19 + (fontSizeLevel - 8) * 5}px` }}>, &nbsp;&nbsp;&nbsp;Profit -</span> <span className={`relative px-[3px] text-green-300 `} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{filteredTradeData.filter(trade => trade.Pl_after_comm > 0 && trade.Type === "close").length}</span>

//               <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80 font-semibold`} style={{ fontSize: `${19 + (fontSizeLevel - 8) * 5}px` }}>,&nbsp;&nbsp;&nbsp; Loss -</span> <span className="text-[30px] text-red-400" style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{filteredTradeData.filter(trade => trade.Pl_after_comm < 0 && trade.Type === "close").length}</span>
              
//             </>
//           ),

// Journey_Stats_Running: (
//             <>
//             <span title="Journey Detail" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>Journey Stats&nbsp;</span>
//               <span title="Journey Detail" className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}>👇&nbsp;</span>
//                             <div style={{ height: '14px' }} />

//               <span className="text-[20px] font-semibold opacity-70 text-center" style={{ fontSize: `${20 + (fontSizeLevel - 8) * 5}px` }}>PJ -&nbsp;</span>
//               <span className={`text-green-300 text-[30px]text-center`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{filteredTradeData.filter(trade => trade.Profit_journey === true && trade.Pl_after_comm > 0 && trade.Type === "running").length}</span>
//               <span className="text-[20px] font-semibold opacity-70 text-center" style={{ fontSize: `${20 + (fontSizeLevel - 8) * 5}px` }}>  &nbsp;&nbsp;&nbsp;CJ -&nbsp;</span>
//               <span className="text-yellow-300 text-[30px] text-center" style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{filteredTradeData.filter(trade => trade.Commision_journey === true && trade.Pl_after_comm > 0 && trade.Type === "running" && trade.Profit_journey === false).length}</span>
//               <span className="text-[20px] font-semibold opacity-70 text-center"  style={{ fontSize: `${20 + (fontSizeLevel - 8) * 5}px` }}> &nbsp;&nbsp;BC- &nbsp;</span>
//               <span className={`text-red-400 text-[30px] text-center`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{filteredTradeData.filter(trade => trade.Pl_after_comm < 0 && trade.Type === "running").length}</span>
//             </>
//           ),
// Client_Stats: (
//             <>
//              <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-80 font-semibold`} style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}> Clients&nbsp;&nbsp; : &nbsp;&nbsp;</span>
//               <span className="text-[30px]" style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{machines.filter(machine => machine.Active).length}</span>
//               &nbsp;<span className="text-[30px]"  style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}> &nbsp; out of </span>&nbsp;
//               <span className="text-[30px]" style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{machines.length}</span>
//             </>
//           ),
// Min_Close_Profit: (
//             <>
//              <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}> Min Close Profit&nbsp;&nbsp;:&nbsp;&nbsp;</span>
//               <span className={`text-green-300 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{filteredTradeData.filter(trade => trade.Min_close === "Min_close" && trade.Type === "close" && trade.Pl_after_comm > 0).length}</span>
//               &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=&nbsp;&nbsp;$&nbsp;&nbsp;</span>
//               <span className={`${minCloseProfitVlaue >= 0 ? "text-green-300" : "text-red-400"} text-[35px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{minCloseProfitVlaue}</span>
//             </>
//           ),
// Min_Close_Loss: (
//             <>
//              <span className={`relative px-[3px] text-yellow-300 font-semibold opacity-70 font-semibold`} style={{ fontSize: `${24 + (fontSizeLevel - 8) * 5}px` }}> Min Close Loss&nbsp;&nbsp;:&nbsp;&nbsp;</span>
//               <span className={`text-red-400 text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{filteredTradeData.filter(trade => trade.Min_close === "Min_close" && trade.Type === "close" && trade.Pl_after_comm < 0).length}</span>
//               &nbsp;&nbsp;<span style={{ fontSize: `${25 + (fontSizeLevel - 8) * 5}px` }}>=&nbsp;&nbsp;$&nbsp;&nbsp;</span>
//               <span className={`${minCloseLossVlaue >= 0 ? "text-green-300" : "text-red-400"} text-[30px]`} style={{ fontSize: `${30 + (fontSizeLevel - 8) * 5}px` }}>{minCloseLossVlaue}</span>
//             </>
//           ),
  }));
// Update dependency array to refresh on filteredTradeData, selectedBox, fontSizeLevel
}, [filteredTradeData, selectedBox, fontSizeLevel]);

useEffect(() => {
  const savedSignals = localStorage.getItem("selectedSignals");
  const savedMachines = localStorage.getItem("selectedMachines");

  if (savedSignals) {
    const parsed = JSON.parse(savedSignals);
    const merged = {
      "2POLE_IN5LOOP": true,
      "IMACD": true,
      "2POLE_Direct_Signal": true,
      "HIGHEST SWING HIGH": true,
      "LOWEST SWING LOW": true,
      "NORMAL SWING HIGH": true,
      "NORMAL SWING LOW": true,
      "ProGap": true,
      "CrossOver": true,
      "Spike": true,
      "Kicker": true,
      ...parsed,
    };
    setSelectedSignals(merged);
    const allSelected = Object.values(merged).every((val) => val === true);
    setSignalToggleAll(!allSelected); // ✅ sync toggle button state
  }

  if (savedMachines) {
    setSelectedMachines(JSON.parse(savedMachines));
  }
}, []);
// Optimized toggle handlers
const toggleMachine = useCallback((machineId) => {
  setSelectedMachines(prev => {
    const key = toMachineKey(machineId);
    const updated = { ...prev, [key]: !prev[key] };
    localStorage.setItem("selectedMachines", JSON.stringify(updated));
    return updated;
  });
}, [toMachineKey]);




useEffect(() => {
  if (signalRadioMode) {
    const selected = Object.keys(selectedSignals).find((key) => selectedSignals[key]);
    if (selected) {
      const updated = {};
      Object.keys(selectedSignals).forEach((key) => {
        updated[key] = key === selected;
      });
      setSelectedSignals(updated);
      localStorage.setItem("selectedSignals", JSON.stringify(updated));
    }
  }
}, [signalRadioMode]);   

useEffect(() => {
  if (intervalRadioMode) {
    const selected = Object.keys(selectedIntervals).find(key => selectedIntervals[key]);
    if (selected) {
      const updated = {};
      Object.keys(selectedIntervals).forEach((key) => {
        updated[key] = key === selected;
      });
      setSelectedIntervals(updated);
      localStorage.setItem("selectedIntervals", JSON.stringify(updated));
    }
  }
}, [intervalRadioMode]);                         

  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('theme');
    if (saved) return saved === 'dark';
    // Default: match system
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  }, [darkMode]);

  // Sync dark mode with localStorage changes (e.g., from reports or another tab)
  useEffect(() => {
    const handleStorage = (e) => {
      if (e.key === 'theme') {
        setDarkMode(e.newValue === 'dark');
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const [trades, setTrades] = useState([]);

  useEffect(() => {
    const fetchTrades = async () => {
      if (typeof window !== "undefined" && window.location?.hostname?.includes("github.io") && !getApiBaseUrl()) return;
      const res = await apiFetch("/api/trades");
      const data = await res.json();
      
      setTrades(data.trades || []);
    };
    fetchTrades();
  }, []);

  if (authChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0f0f0f]">
        <div className="text-gray-400">Checking session…</div>
      </div>
    );
  }
  if (!isLoggedIn) {
    return <LoginPage onLogin={() => setLoggedIn(true)} />;
  }

  const authContextValue = {
    logout: async () => {
      await logoutApi();
      setLoggedIn(false);
      setShowSessionWarning(false);
    },
  };

  return (
      <AuthContext.Provider value={authContextValue}>
      {showSessionWarning && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60" role="dialog" aria-modal="true" aria-labelledby="session-warning-title">
          <div className="bg-white dark:bg-[#222] rounded-xl p-6 max-w-sm w-full shadow-xl border border-gray-200 dark:border-gray-700 mx-4">
            <h2 id="session-warning-title" className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Session expired</h2>
            <p className="text-gray-600 dark:text-gray-300 text-sm mb-4">Please sign in again.</p>
            <button
              type="button"
              onClick={() => { setLoggedIn(false); setShowSessionWarning(false); }}
              className="w-full py-2 rounded-lg bg-teal-600 hover:bg-teal-700 text-white font-semibold"
            >
              OK
            </button>
          </div>
        </div>
      )}
      <Routes>
        <Route path="/chart-grid" element={<ChartGridPage />} />
        <Route path="/custom-chart-grid" element={<CustomChartGrid trades={filteredTradeData} />} />
        <Route path="/reports" element={<ReportDashboard />} />
        <Route path="/reports/list" element={<ListViewPage />} />
        <Route path="/live-trade-view" element={<LiveTradeViewPage />} />
        <Route path="/live-running-trades" element={<LiveRunningTradesPage />} />
        <Route path="/pages/group-view" element={<GroupViewPage />} />
        <Route path="/trades" element={<TradeComparePage />} />
        {/* <Route path="/settings" element={<SettingsPage />} /> */}
        <Route path="/*" element={
          <>
            {/* Sticky LAB section at the very top of the app, outside the main flex container */}
            <div className="sticky top-0 z-40 flex justify-center items-center border-b border-gray-200 dark:border-gray-700 shadow-sm bg-[#f5f6fa] dark:bg-black" style={{ minHeight: '80px', height: '80px', padding: '0 16px' }}>
              {/* Refresh controls (left) */}
              <div className="absolute left-4 top-3 z-20">
                <RefreshControls
                  onRefresh={refreshAllData}
                  storageKey="app_main"
                  initialIntervalSec={20}
                  initialAutoOn={true}
                />
              </div>
              {/* Light/Dark mode toggle button */}
              <button
                onClick={() => setDarkMode(dm => !dm)}
                className="absolute right-8 top-3 z-20 p-2 rounded-full bg-white/80 dark:bg-gray-800/80 shadow hover:scale-110 transition-all"
                title={darkMode ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
                style={{ fontSize: 24 }}
              >
                {darkMode ? '🌞' : '🌙'}
              </button>
              <LogoutButton className="absolute right-36 top-3 z-20 px-2 py-1 rounded-full bg-white/80 dark:bg-gray-800/80 shadow hover:scale-105 transition-all text-sm font-semibold text-red-600 dark:text-red-400" />
              <button
                onClick={() => setIsSoundOpen(true)}
                className="absolute right-24 top-3 z-20 px-2 py-1 rounded-full bg-white/80 dark:bg-gray-800/80 shadow hover:scale-105 transition-all text-sm font-semibold"
                title="Sound & New trades settings"
              >
                🔊 Sound
              </button>
              {/* SVG Graph Background (animated) */}
              <AnimatedGraphBackground width={400} height={48} opacity={0.4} />
              {/* LAB text */}
              <h1
                className="relative z-10 text-5xl font-extrabold text-center bg-gradient-to-r from-blue-500 via-pink-500 to-yellow-400 bg-clip-text text-transparent drop-shadow-lg tracking-tight animate-pulse"
                style={{
                  WebkitTextStroke: '1px #222',
                  textShadow: '0 4px 24px rgba(0,0,0,0.18)',
                }}
              >
                LAB
                <span className="block w-16 h-1 mx-auto mt-2 rounded-full bg-gradient-to-r from-blue-400 via-pink-400 to-yellow-300 animate-gradient-x"></span>
              </h1>
            </div>
            <div className="flex">
              {/* Sidebar */}
              <Sidebar isOpen={isSidebarOpen} toggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)} />
              <div className={`flex-1 min-h-screen transition-all duration-300 ${isSidebarOpen ? "ml-64" : "ml-20"} overflow-hidden relative bg-[#f5f6fa] dark:bg-black`}>
                {/* Main content area, no extra margin-top */}
                <div className="p-8 pt-2 overflow-x-auto">
                  {corsError && (
                    <div className="mb-4 p-4 rounded-lg bg-red-100 dark:bg-red-900/40 border border-red-400 dark:border-red-600 text-red-900 dark:text-red-100 text-sm">
                      <strong className="block mb-2">❌ CORS Error: Cloud server not allowing GitHub Pages origin</strong>
                      <p className="mb-2">The cloud server (150.241.244.130) is blocking requests from <code className="bg-red-200/60 dark:bg-red-800/60 px-1 rounded">https://loveleet.github.io</code>.</p>
                      <p className="mb-2"><strong>Fix:</strong> Deploy the latest <code className="bg-red-200/60 dark:bg-red-800/60 px-1 rounded">server/server.js</code> to the cloud (it has CORS for GitHub Pages) and restart the Node app.</p>
                      <ol className="list-decimal list-inside space-y-1 mt-2 text-xs">
                        <li>From laptop: <code className="bg-red-200/60 dark:bg-red-800/60 px-1 rounded">export DEPLOY_HOST=root@150.241.244.130 && ./scripts/deploy-to-server.sh</code></li>
                        <li>Or manually: <code className="bg-red-200/60 dark:bg-red-800/60 px-1 rounded">scp server/server.js root@150.241.244.130:/opt/apps/lab-trading-dashboard/server/</code></li>
                        <li>On cloud: <code className="bg-red-200/60 dark:bg-red-800/60 px-1 rounded">sudo systemctl restart lab-trading-dashboard</code></li>
                        <li>Verify: <code className="bg-red-200/60 dark:bg-red-800/60 px-1 rounded">curl -s http://localhost:10000/api/server-info</code> should show <code className="bg-red-200/60 dark:bg-red-800/60 px-1 rounded">hasGitHubPagesOrigin: true</code></li>
                      </ol>
                    </div>
                  )}
                  {localServerDown && (
                    <div className="mb-4 p-4 rounded-lg bg-amber-100 dark:bg-amber-900/40 border border-amber-400 dark:border-amber-600 text-amber-900 dark:text-amber-100 text-sm">
                      <strong className="block mb-2">Local server not running</strong>
                      <p className="mb-2">The app is trying to use the local API at <code className="bg-amber-200/60 dark:bg-amber-800/60 px-1 rounded">localhost:10000</code> (via Vite proxy), but the connection was refused. Start the Node server in <code className="bg-amber-200/60 dark:bg-amber-800/60 px-1 rounded">lab-trading-dashboard/server</code> or use cloud data.</p>
                      <button
                        type="button"
                        onClick={() => {
                          setLocalhostUseCloudFallback(true);
                          setLocalServerDown(false);
                          setApiUnreachable(false);
                          refreshAllData();
                        }}
                        className="mt-2 px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-700 text-white text-sm font-medium"
                      >
                        Use cloud data
                      </button>
                    </div>
                  )}
                  {apiUnreachable && !corsError && !localServerDown && (
                    <div className="mb-4 p-4 rounded-lg bg-amber-100 dark:bg-amber-900/40 border border-amber-400 dark:border-amber-600 text-amber-900 dark:text-amber-100 text-sm">
                      <strong className="block mb-2">API unreachable</strong>
                      <p className="mb-2">The backend at the current API URL could not be reached. Check that the server is running and that <code className="bg-amber-200/60 dark:bg-amber-800/60 px-1 rounded">API_BASE_URL</code> is set to your cloud URL (e.g. <code className="bg-amber-200/60 dark:bg-amber-800/60 px-1 rounded">http://150.241.244.130:10000</code>).</p>
                      <p className="text-xs">Hard-refresh (Ctrl+Shift+R) after fixing the URL or restarting the server.</p>
                    </div>
                  )}
                  {typeof window !== "undefined" && window.location?.hostname?.includes("github.io") && !apiBaseForBanner && !apiUnreachable && (
                    <div className="mb-4 p-4 rounded-lg bg-blue-100 dark:bg-blue-900/40 border border-blue-400 dark:border-blue-600 text-blue-900 dark:text-blue-100 text-sm">
                      <strong className="block mb-2">API not configured for GitHub Pages</strong>
                      <p className="mb-2">To load data here, set your backend URL (cloud IP or domain) and redeploy:</p>
                      <ol className="list-decimal list-inside space-y-1 mt-2 text-xs">
                        <li>Add secret <a href="https://github.com/Loveleet/lab_live/settings/secrets/actions" target="_blank" rel="noopener noreferrer" className="underline font-medium">Settings → Secrets → Actions</a> → <code className="bg-blue-200/60 dark:bg-blue-800/60 px-1 rounded">API_BASE_URL</code> = your backend URL (e.g. <code className="bg-blue-200/60 dark:bg-blue-800/60 px-1 rounded">http://150.241.244.130:10000</code>, no trailing slash).</li>
                        <li><a href="https://github.com/Loveleet/lab_live/actions/workflows/deploy-frontend-pages.yml" target="_blank" rel="noopener noreferrer" className="underline font-medium">Run &quot;Deploy frontend to GitHub Pages&quot;</a>, then hard-refresh this page.</li>
                      </ol>
                    </div>
                  )}
                  {demoDataHint && (
                    <div className="mb-4 p-4 rounded-lg bg-orange-100 dark:bg-orange-900/40 border border-orange-400 dark:border-orange-600 text-orange-900 dark:text-orange-100 text-sm">
                      <strong className="block mb-2">Get real data on this cloud site</strong>
                      <p className="mb-2">{demoDataHint}</p>
                      <ol className="list-decimal list-inside space-y-1 mt-2 text-xs">
                        <li>On this server edit env: <code className="bg-orange-200/60 dark:bg-orange-800/60 px-1 rounded">sudo nano /etc/lab-trading-dashboard.env</code></li>
                        <li>Add <code className="bg-orange-200/60 dark:bg-orange-800/60 px-1 rounded">DATABASE_URL=&apos;postgres://user:pass@host:5432/dbname&apos;</code> (your Postgres URL) or set DB_HOST, DB_USER, DB_PASSWORD, DB_NAME</li>
                        <li>Restart: <code className="bg-orange-200/60 dark:bg-orange-800/60 px-1 rounded">sudo systemctl restart lab-trading-dashboard</code> → wait ~30s and refresh</li>
                      </ol>
                    </div>
                  )}
                  {Array.isArray(tradeData) && tradeData.length === 0 && !demoDataHint && !(typeof window !== "undefined" && window.location?.hostname?.includes("github.io") && !apiBaseForBanner) && (
                    <div className="mb-4 p-3 rounded-lg bg-amber-100 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700 text-amber-800 dark:text-amber-200 text-sm">
                      <strong>No trade records in database.</strong> Table <code className="bg-amber-200/50 dark:bg-amber-800/50 px-1 rounded">alltraderecords</code> is empty. Machines and pairstatus are loading from the same DB. To see trades, add data or copy the database (see docs or <code className="bg-amber-200/50 dark:bg-amber-800/50 px-1 rounded">/api/debug</code> for counts).
                    </div>
                  )}
                  <div className="flex justify-end mb-2">
                    <button
                      onClick={() => setFilterVisible((v) => !v)}
                      className="text-xs px-3 py-1 rounded-full bg-gray-200 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 hover:bg-gray-300 dark:hover:bg-gray-700 shadow"
                    >
                      {filterVisible ? "Hide Filters" : "Show Filters"}
                    </button>
                  </div>
                  {filterVisible && (
                    <TradeFilterPanel
                      selectedSignals={selectedSignals}
                      setSelectedSignals={setSelectedSignals}
                      selectedMachines={selectedMachines}
                      setSelectedMachines={setSelectedMachines}
                      selectedIntervals={selectedIntervals}
                      setSelectedIntervals={setSelectedIntervals}
                      selectedActions={selectedActions}
                      setSelectedActions={setSelectedActions}
                      fromDate={fromDate}
                      toDate={toDate}
                      setFromDate={setFromDate}
                      setToDate={setToDate}
                      includeMinClose={includeMinClose}
                      setIncludeMinClose={setIncludeMinClose}
                      signalRadioMode={signalRadioMode}
                      setSignalRadioMode={setSignalRadioMode}
                      machineRadioMode={machineRadioMode}
                      setMachineRadioMode={setMachineRadioMode}
                      intervalRadioMode={intervalRadioMode}
                      setIntervalRadioMode={setIntervalRadioMode}
                      actionRadioMode={actionRadioMode}
                      setActionRadioMode={setActionRadioMode}
                      liveFilter={liveFilter}
                      setLiveFilter={setLiveFilter}
                      liveRadioMode={liveRadioMode}
                      setLiveRadioMode={setLiveRadioMode}
                      signalToggleAll={signalToggleAll}
                      setSignalToggleAll={setSignalToggleAll}
                      machineToggleAll={machineToggleAll}
                      setMachineToggleAll={setMachineToggleAll}
                      machines={machines}
                      dateKey={dateKey}
                      setDateKey={setDateKey}
                      assignedCount={getFilteredForTitle["Assigned_New"]?.length || 0}
                    />
                  )}
        <div className="flex flex-wrap items-start gap-3 ml-0 md:ml-6">
  {/* Controls block */}
  <div className="flex items-center gap-3 flex-none">
    <span className="text-sm md:text-base lg:text-lg font-semibold text-black">Layout:</span>
    <button
      onClick={() => {
        const newOption = Math.max(1, layoutOption - 1);
        setLayoutOption(newOption);
        localStorage.setItem("layoutOption", newOption);
      }}
      className="bg-gray-300 hover:bg-gray-400 text-black px-2 py-1 md:px-3 md:py-1.5 rounded text-sm md:text-base"
    >
      ➖
    </button>
    <button
      onClick={() => {
        const newOption = Math.min(14, layoutOption + 1);
        setLayoutOption(newOption);
        localStorage.setItem("layoutOption", newOption);
      }}
      className="bg-gray-300 hover:bg-gray-400 text-black px-2 py-1 md:px-3 md:py-1.5 rounded text-sm md:text-base"
    >
      ➕
    </button>

    <span className="hidden md:inline px-2 text-gray-400">|</span>

    <div className="flex items-center gap-3">
      <button
        onClick={() =>
          setFontSizeLevel((prev) => {
            const newLevel = Math.max(1, prev - 1);
            localStorage.setItem("fontSizeLevel", newLevel);
            return newLevel;
          })
        }
        className="bg-gray-300 hover:bg-gray-400 text-black px-2 py-1 md:px-3 md:py-1.5 rounded text-sm md:text-base"
        aria-label="Decrease font size"
      >
        ➖
      </button>
      <span className="text-sm md:text-base lg:text-lg font-semibold text-black">
        Font: {fontSizeLevel}
      </span>
      <button
        onClick={() =>
          setFontSizeLevel((prev) => {
            const newLevel = Math.min(30, prev + 1);
            localStorage.setItem("fontSizeLevel", newLevel);
            return newLevel;
          })
        }
        className="bg-gray-300 hover:bg-gray-400 text-black px-2 py-1 md:px-3 md:py-1.5 rounded text-sm md:text-base"
        aria-label="Increase font size"
      >
        ➕
      </button>
    </div>

    {/* Live condition badges (BUY/SELL) */}
    {(() => {
      const toBool = (v) => {
        if (v === true || v === "true" || v === 1 || v === "1") return true;
        if (typeof v === "string") {
          const n = parseFloat(v);
          if (!Number.isNaN(n)) return n > 0;
        }
        return false;
      };
      const buy = toBool(activeLossFlags?.buy ?? activeLossFlags?.buy_condition ?? activeLossFlags?.buyflag);
      const sell = toBool(activeLossFlags?.sell ?? activeLossFlags?.sell_condition ?? activeLossFlags?.sellflag);
      const Badge = ({ label, on }) => (
        <span
          className={`px-2 py-1 rounded-full text-xs font-bold border ${
            on
              ? "bg-green-500/90 text-white border-green-600 animate-pulse ring-2 ring-green-300"
              : "bg-gray-200 text-gray-700 border-gray-300 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700"
          }`}
          title={`${label} condition ${on ? "ACTIVE" : "inactive"}`}
        >
          {on ? `LIVE ${label}` : `${label} OFF`}
        </span>
      );
      return (
        <div className="flex items-center gap-2 ml-1">
          <Badge label="BUY" on={buy} />
          <Badge label="SELL" on={sell} />
        </div>
      );
    })()}

    <span className="text-green-600 text-[14px] md:text-[16px] lg:text-[18px] font-bold">
      ➤ Assigned New:
    </span>
    <span
      className="text-red-600 text-[24px] md:text-[34px] lg:text-[40px] font-bold cursor-pointer hover:underline"
      title="Click to view Assigned Trades"
      onClick={() => {
        setSelectedBox((prev) => {
          const next = prev === "Assigned_New" ? null : "Assigned_New";
          if (next) {
            setActiveSubReport("assign");
            setTimeout(() => {
              const section = document.getElementById("tableViewSection");
              if (section) section.scrollIntoView({ behavior: "smooth" });
            }, 0);
          }
          return next;
        });
      }}
    >
      {filteredTradeData.filter((trade) => trade.type === "assign" || trade.type === "back_close").length}
    </span>
  </div>

  {/* SuperTrend + EMA group (inline if space; wraps under if not) */}
  <div className="flex flex-wrap items-start gap-4 flex-1 min-w-[280px]">
    {/* SuperTrend: fixed width on sm+; full width on xs */}
    <div className="w-full sm:w-[300px] md:w-[360px] shrink-0">
      <SuperTrendPanel data={superTrendData} />
    </div>

    {/* EMA Grid */}
    {emaTrends && (
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 flex-1 min-w-[280px]">
        {(() => {
          // Smooth color from white -> target before 90 (light ramp), full at 90+
          const pctColor = (valNum, isBull, isBear) => {
            const v = Number(valNum);
            if (Number.isNaN(v)) return { color: "rgb(255,255,255)" };
            const tRaw = Math.max(0, Math.min(v / 90, 1));
            const t = Math.pow(tRaw, 0.6);
            const target = isBull ? [34, 197, 94] : isBear ? [239, 68, 68] : [255, 255, 255];
            const r = Math.round(255 + (target[0] - 255) * t);
            const g = Math.round(255 + (target[1] - 255) * t);
            const b = Math.round(255 + (target[2] - 255) * t);
            return { color: `rgb(${r}, ${g}, ${b})` };
          };

          const EmaBox = ({ minsLabelFull, minsLabelShort, minsLabelTiny, trendText, pct }) => {
            const val = Number(pct);
            const trend = (trendText || "").toLowerCase();
            const isBull = trend.includes("bull");
            const isBear = trend.includes("bear");
            const hot = !Number.isNaN(val) && val >= 90;

            // Base bluish bg
            const baseBox =
              "w-full min-w-0 flex items-center justify-between px-3 md:px-4 lg:px-5 py-2 md:py-2.5 lg:py-3 rounded-lg border transition-all duration-200 ease-out " +
              "bg-blue-50 dark:bg-blue-950/40 border-blue-200 dark:border-blue-900";

            // Hot (≥90): tint + ring + shadow + scale + slight blink
            const hotDecor = hot
              ? isBear
                ? " bg-red-50 dark:bg-red-950/40 ring-2 ring-red-300 dark:ring-red-800 shadow-md scale-[1.04] animate-pulse"
                : isBull
                ? " bg-green-50 dark:bg-green-950/40 ring-2 ring-green-300 dark:ring-green-800 shadow-md scale-[1.04] animate-pulse"
                : " animate-pulse"
              : "";

            const boxClass = `${baseBox} ${hotDecor}`.trim();

            // % sizing & color
            const pctSize = hot
              ? "text-base md:text-lg lg:text-xl xl:text-2xl"
              : "text-sm md:text-base lg:text-lg xl:text-xl";
            const pctStyleColor = hot
              ? { color: isBull ? "rgb(34,197,94)" : isBear ? "rgb(239,68,68)" : "rgb(255,255,255)" }
              : pctColor(val, isBull, isBear);

            // Ultra-thin white outline on ALL text only when hot
            const hotStrokeStyle = hot
              ? { WebkitTextStroke: "0.15px rgba(255,255,255,0.85)", textShadow: "0 0 0.1px rgba(255,255,255,0.7)" }
              : {};

            // Arrow before label
            const Arrow = () => (
              <span className="inline-flex items-center text-base md:text-lg lg:text-xl flex-none shrink-0">
                {isBull && <span className="text-green-500 leading-none">▲</span>}
                {isBear && <span className="text-red-500 leading-none">▼</span>}
              </span>
            );

            // Trend words (bullish/bearish) after EMA (visible from sm+; truncates first)
            const TrendWord = () => (
              <span
                className={`font-bold ${isBull ? "text-green-600" : isBear ? "text-red-600" : "text-black dark:text-white"} truncate hidden sm:inline`}
                title={trendText}
              >
                {trendText}
              </span>
            );

            return (
              <div className={boxClass} style={hotStrokeStyle}>
                {/* LEFT: Arrow, then EMA label, then bullish/bearish */}
                <div className="flex items-center gap-2 sm:gap-3 lg:gap-4 min-w-0 flex-1 overflow-hidden">
                  <Arrow />
                  {/* Interval label variants */}
                  <span className="text-blue-700 dark:text-blue-200 font-bold flex-none shrink-0 hidden lg:block whitespace-nowrap">
                    {minsLabelFull /* "EMA 1m:" */}
                  </span>
                  <span className="text-blue-700 dark:text-blue-200 font-bold flex-none shrink-0 hidden sm:block lg:hidden whitespace-nowrap">
                    {minsLabelShort /* "1m" */}
                  </span>
                  <span className="text-blue-700 dark:text-blue-200 font-bold flex-none shrink-0 block sm:hidden whitespace-nowrap">
                    {minsLabelTiny /* "1" */}
                  </span>
                  <TrendWord />
                </div>

                {/* RIGHT: Percentage — NEVER shrinks */}
                <span
                  className={`font-extrabold ${pctSize} text-right leading-none ml-3 flex-none shrink-0`}
                  style={{
                    ...pctStyleColor,
                    minWidth: "76px",
                    width: "max(76px, 5.5ch)",
                    whiteSpace: "nowrap",
                    display: "inline-block",
                  }}
                  title={`${!Number.isNaN(val) ? val.toFixed(2) : pct}%`}
                >
                  {!Number.isNaN(val) ? val.toFixed(2) : pct}%
                </span>
              </div>
            );
          };

          return (
            <>
              <EmaBox
                minsLabelFull="EMA 1m:"
                minsLabelShort="1m"
                minsLabelTiny="1"
                trendText={emaTrends.overall_ema_trend_1m}
                pct={emaTrends.overall_ema_trend_percentage_1m}
              />
              <EmaBox
                minsLabelFull="EMA 5m:"
                minsLabelShort="5m"
                minsLabelTiny="5"
                trendText={emaTrends.overall_ema_trend_5m}
                pct={emaTrends.overall_ema_trend_percentage_5m}
              />
              <EmaBox
                minsLabelFull="EMA 15m:"
                minsLabelShort="15m"
                minsLabelTiny="15"
                trendText={emaTrends.overall_ema_trend_15m}
                pct={emaTrends.overall_ema_trend_percentage_15m}
              />
            </>
          );
        })()}
      </div>
    )}
  </div>
</div>


                  {/* ✅ Dashboard Cards */}
                  {metrics && (
                    <div
                      className="grid gap-6 w-full px-2 py-4"
                      style={{
                        gridTemplateColumns: `repeat(${layoutOption}, minmax(0, 1fr))`,
                        transition: 'all 0.3s ease-in-out',
                      }}
                    >
                      {Object.entries(metrics).map(([title, value]) => {
                        const normalizedKey = title.trim().replace(/\s+/g, "_");
                        const showSticker = normalizedKey === "Direct_Running_Stats";
                        const mostRecent = showSticker ? (newDirectRunning || [])
                          .map(t =>
                            t.fetcher_trade_time ||
                            t.Fetcher_Trade_time ||
                            t.fetch_time ||
                            t.candel_time ||
                            t.candle_time ||
                            t.timestamp ||
                            t.created_at
                          )
                          .filter(Boolean)
                          .sort((a, b) => new Date(b) - new Date(a))[0] : null;
                        const lastTs = mostRecent ? (moment.utc(mostRecent).isValid() ? moment.utc(mostRecent).format("HH:mm") + " UTC" : null) : null;
                        const stickerText = showSticker && (newDirectRunning?.length > 0)
                          ? `New: ${newDirectRunning.length}${lastTs ? ` • Last ${lastTs}` : ""}`
                          : null;
                        return (
                          <div key={normalizedKey} className="relative">
                            <DashboardCard
                              title={title}
                              value={value}
                              isSelected={selectedBox === normalizedKey}
                              onClick={() => {
                                const hasData = getFilteredForTitle[normalizedKey];
                                setSelectedBox(prev =>
                                  prev === normalizedKey || !hasData ? null : normalizedKey
                                );
                              }}
                              sticker={showSticker ? stickerText : null}
                              onStickerClick={() => {
                                setSelectedBox("Direct_Running_New");
                                setActiveSubReport("running");
                                setTimeout(() => {
                                  const section = document.getElementById("tableViewSection");
                                  if (section) section.scrollIntoView({ behavior: "smooth" });
                                }, 0);
                              }}
                              filteredTradeData={filteredTradeData}
                              className="bg-white dark:bg-[#181a20] border border-gray-200 dark:border-gray-800"
                            />
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {/* ChartGrid Component */}
                  {/* Removed ChartGrid component rendering and its logic */}
                  {/* ✅ Machine Filter with Mode Toggle */}
                  {/* --- Render metrics/cards here as before --- */}
                  {/* ✅ TableView always rendered below dashboard, default to Total Profit if nothing selected */}
                  <div className="mt-6">
                    {selectedBox && (() => {
                      const normalizedKey = selectedBox?.trim().replace(/\s+/g, "_");
                      const data = normalizedKey === "Direct_Running_New" ? newDirectRunning : getFilteredForTitle[normalizedKey];
                      if (data && data.length > 0) {
                        return (
                          <div className="mt-6">
                            <TableView
                              title={selectedBox}
                              tradeData={data}
                              clientData={clientData}
                              logData={logData}
                              activeSubReport={activeSubReport}
                              setActiveSubReport={setActiveSubReport}
                            />
                          </div>
                        );
                      } else {
                        return (
                          <p className="text-center text-gray-500 mt-4">
                            ⚠️ No relevant data available for {selectedBox.replace(/_/g, " ")} (Found {data?.length || 0} items)
                          </p>
                        );
                      }
                    })()}
                  </div>
                  <div className="my-4">
                    {/* Removed Open Custom Chart Grid (New Tab) button */}
                  </div>
                </div>
              </div>
            </div>
            <SoundSettings
              isOpen={isSoundOpen}
              onClose={() => setIsSoundOpen(false)}
              settings={soundSettings}
              onChange={setSoundSettings}
              availableSignals={availableSignals}
            />
          </>
        } />
      </Routes>
      </AuthContext.Provider>
  );
};

export default App;
