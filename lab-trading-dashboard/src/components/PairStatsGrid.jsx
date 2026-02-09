import React, { useState, useEffect, useRef, useMemo } from 'react';
import PropTypes from 'prop-types';
import PairStatsFilters from './PairStatsFilters';
import { api } from '../config';

const getPairStats = (pair, trades) => {
  const pairTrades = trades.filter(t => t.pair === pair);
const sellCount = pairTrades.filter(t => t.action === 'SELL').length;
const buyCount = pairTrades.filter(t => t.action === 'BUY').length;
const hedgeCount = pairTrades.filter(t => {
  const isHedge = t.hedge === true || t.hedge === "true" || t.hedge === 1 || t.hedge === "1" || 
                 (typeof t.hedge === 'string' && parseFloat(t.hedge) > 0);
  return isHedge;
}).length;
const runningCount = pairTrades.filter(t => t.type === 'running' || t.type === 'assigned').length;
const profitClosedCount = pairTrades.filter(t => t.type === 'close' && t.pl_after_comm > 0).length;
const totalProfitAmount = pairTrades.filter(t => t.pl_after_comm > 0).reduce((sum, t) => sum + (parseFloat(t.pl_after_comm) || 0), 0);
  const totalCount = pairTrades.length;
  return {
    sellCount,
    buyCount,
    hedgeCount,
    runningCount,
    profitClosedCount,
    totalProfitAmount,
    totalCount,
  };
};

function flexibleMatch(needle, haystack) {
  needle = needle.toLowerCase();
  haystack = haystack.toLowerCase();
  let j = 0;
  for (let i = 0; i < haystack.length && j < needle.length; i++) {
    if (haystack[i] === needle[j]) j++;
  }
  return j === needle.length;
}

const NOTIF_WINDOWS = [
  { label: '15 min', value: 15 },
  { label: '30 min', value: 30 },
  { label: '1 hr', value: 60 },
  { label: '3 hr', value: 180 },
  { label: '6 hr', value: 360 },
  { label: 'Anytime', value: 10000 },
];

function hasRecentTrade(trades, pair, notifWindow) {
  const now = Date.now();
  const windowMs = notifWindow * 60 * 1000;
  return trades.some(t => {
    if (t.pair !== pair) return false;
    // Try both Candel_time and Candle_Time
    const timeStr = t.candel_time || t.candle_time;
    if (!timeStr) return false;
    const tradeTime = new Date(timeStr.replace(' ', 'T') + 'Z').getTime();
    return now - tradeTime <= windowMs;
  });
}

// Add a function to count recent trades for a pair
function countRecentTrades(trades, pair, notifWindow) {
  const now = Date.now();
  const windowMs = notifWindow * 60 * 1000;
  return trades.filter(t => {
    if (t.pair !== pair) return false;
    const timeStr = t.candel_time || t.candle_time;
    if (!timeStr) return false;
    const tradeTime = new Date(timeStr.replace(' ', 'T') + 'Z').getTime();
    return now - tradeTime <= windowMs;
  }).length;
}

// Add a function to compute total hedge P/L
function getHedgePL(pair, trades) {
  return trades
      .filter(t => t.pair === pair && t.hedge === true && typeof t.pl_after_comm === 'number')
  .reduce((sum, t) => sum + t.pl_after_comm, 0);
}

// Signal options for filter
const SIGNAL_OPTIONS = [
  { label: '📡 Signal', value: 'signal' },
  { label: '☑️ Radio', value: 'radio' },
  { label: '✅ All', value: 'all' },
  { label: '2P_L', value: '2P_L' },
  { label: 'IMACD', value: 'IMACD' },
  { label: '2P_DS', value: '2P_DS' },
  { label: 'HSH', value: 'HSH' },
  { label: 'LSL', value: 'LSL' },
  { label: 'NSH', value: 'NSH' },
  { label: 'NSL', value: 'NSL' },
  { label: 'PG', value: 'PG' },
  { label: 'CO', value: 'CO' },
  { label: 'SP', value: 'SP' },
];

// Signal label mapping (copied from TradeFilterPanel)
const signalLabels = {
  "2POLE_IN5LOOP": "2P_L",
  "IMACD": "IMACD",
  "2POLE_Direct_Signal": "2P_DS",
  "HIGHEST SWING HIGH": "HSH",
  "LOWEST SWING LOW": "LSL",
  "NORMAL SWING HIGH": "NSH",
  "NORMAL SWING LOW": "NSL",
  "ProGap": "PG",
  "CrossOver": "CO",
  "Spike": "SP",
  "Kicker": "Kicker",
};

// Canonical signal keys (from signalLabels)
const canonicalSignalKeys = [
  "2POLE_IN5LOOP",
  "IMACD",
  "2POLE_Direct_Signal",
  "HIGHEST SWING HIGH",
  "LOWEST SWING LOW",
  "NORMAL SWING HIGH",
  "NORMAL SWING LOW",
  "ProGap",
  "CrossOver",
  "Spike",
  "Kicker"
];

// Sort options for the grid
const SORT_OPTIONS = [
  { value: 'latest', label: '🆕 Latest Running' },
  { value: 'alpha', label: '🔤 Alphabetical' },
  { value: 'hedgeCount', label: '🔁 Hedge Count' },
  { value: 'profitCount', label: '💰 Profit Count' },
  { value: 'hedgeAmount', label: '🧮 Hedge Amount' },
  { value: 'profitAmount', label: '📈 Profit Amount' },
  { value: 'total', label: '📊 Total Trades' },
  { value: 'meanPerTrade', label: 'Mean Per Trade (Amount)' },
  { value: 'meanOverall', label: 'Mean Overall (Amount)' },
  { value: 'meanCount', label: 'Mean of Count (Profit - Loss Count)' },
];

// Helper: default sort order per type
const DEFAULT_SORT_ORDERS = {
  latest: false, // desc (most recent first)
  alpha: true,   // asc (A-Z)
  hedgeCount: false, // desc (highest first)
  profitCount: false, // desc (highest first)
  hedgeAmount: false, // desc (most negative first)
  profitAmount: false, // desc (highest first)
  total: false, // desc (highest first)
  meanPerTrade: false, // desc (highest first)
  meanOverall: false, // desc (highest first)
};

// ControlsBox component for unified controls
function ControlsBox({
  search, setSearch,
  sortOption, handleSortChange, sortAsc, handleSortToggle,
  reputationEnabled, setReputationEnabled, reputationMode, setReputationMode, reputationIntensity, setReputationIntensity,
  density, setDensity,
  totalPairs,
  settingsOpen, setSettingsOpen,
  darkMode,
  masterFont, setMasterFont,
  nameFont, setNameFont,
  infoFont, setInfoFont,
  notifWindow, setNotifWindow,
  notifStyle, setNotifStyle,
  notifSize, setNotifSize,
  rankBadgeSize, setRankBadgeSize,
  NOTIF_WINDOWS,
  settingsRef, // <-- add this prop
  showForClubFilter, setShowForClubFilter
}) {
  return (
    <div
      className="flex-1 min-w-[320px] break-inside-avoid rounded-2xl shadow-lg p-4 gap-2 mb-4"
      style={{
        background: darkMode
          ? 'linear-gradient(to bottom right, #0f172a 0%, #334155 100%)'
          : 'linear-gradient(to bottom right, #f8fafc 0%, #e0eafc 100%)',
        border: darkMode ? '1.5px solid #334155' : '1.5px solid #bcd0ee',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        justifyContent: 'space-between',
        minHeight: 120,
      }}
    >
      <div className="flex flex-wrap items-center gap-2 justify-between w-full" style={{ minHeight: 0, padding: '6px 0', margin: '0 0 6px 0' }}>
        <input
          type="text"
          className="px-2 py-1 rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 text-black dark:text-white w-full max-w-xs focus:outline-none focus:ring-2 focus:ring-blue-400"
          placeholder="Search pair..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ fontSize: 13, height: 32 }}
        />
        <select
          value={showForClubFilter}
          onChange={e => setShowForClubFilter(e.target.value)}
          className="px-1 py-1 rounded border bg-white text-black dark:bg-gray-900 dark:text-white"
          style={{ minWidth: 120, fontSize: 13, height: 32 }}
        >
          <option value="All">All (No Filter)</option>
          <option value="Total Closed Stats">Total Closed Stats</option>
          <option value="Direct Closed Stats">Direct Closed Stats</option>
          <option value="Hedge Closed Stats">Hedge Closed Stats</option>
          <option value="Total Running Stats">Total Running Stats</option>
          <option value="Direct Running Stats">Direct Running Stats</option>
          <option value="Hedge Running Stats">Hedge Running Stats</option>
          <option value="Total Stats">Total Stats</option>
          <option value="Buy Sell Stats">Buy Sell Stats</option>
          <option value="Hedge on Hold">Hedge on Hold</option>
        </select>
        <select value={sortOption} onChange={e => handleSortChange(e.target.value)} className="px-1 py-1 rounded border bg-white text-black dark:bg-gray-900 dark:text-white" style={{ fontSize: 13, height: 32 }}>
          {SORT_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select>
        <button
          onClick={handleSortToggle}
          className="px-1 py-1 rounded border"
          title="Toggle Ascending/Descending"
          style={{ fontSize: 13, height: 32 }}
        >
          {sortAsc ? '⬆️' : '⬇️'}
        </button>
        <button
          type="button"
          className={`ml-2 px-3 py-1 rounded-full border font-bold ${reputationEnabled ? 'bg-blue-600 text-white border-blue-700' : 'bg-gray-200 text-gray-700 border-gray-400'}`}
          onClick={() => setReputationEnabled(v => !v)}
          style={{ fontSize: 13, height: 32 }}
        >
          Reputation {reputationEnabled ? 'ON' : 'OFF'}
        </button>
        <div className="flex items-center gap-2">
          <label className={`flex items-center gap-1 ${reputationMode === 'perTrade' && reputationEnabled ? 'animate-pulse-gold' : ''}`}> <input type="radio" name="reputationMode" value="perTrade" checked={reputationMode === 'perTrade'} onChange={() => setReputationMode('perTrade')} disabled={!reputationEnabled} /> <span className="text-xs">Per Trade</span> </label>
          <label className={`flex items-center gap-1 ${reputationMode === 'overall' && reputationEnabled ? 'animate-pulse-blue' : ''}`}> <input type="radio" name="reputationMode" value="overall" checked={reputationMode === 'overall'} onChange={() => setReputationMode('overall')} disabled={!reputationEnabled} /> <span className="text-xs">Overall</span> </label>
        </div>
        {reputationEnabled && (
          <label className="flex items-center gap-2 text-blue-900 dark:text-blue-200 font-semibold">
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={reputationIntensity}
              onChange={e => setReputationIntensity(Number(e.target.value))}
              className="w-32 accent-blue-600"
              style={{ verticalAlign: 'middle' }}
            />
            <span className="ml-2 text-xs">{Math.round(reputationIntensity * 100)}%</span>
          </label>
        )}
        <button
          className={`px-3 py-1 rounded border text-xs font-bold transition-all ${density === 'spacious' ? 'bg-blue-100 dark:bg-blue-900 border-blue-400 text-blue-700 dark:text-blue-200' : 'bg-gray-100 dark:bg-gray-800 border-gray-400 text-gray-700 dark:text-gray-200'}`}
          onClick={() => setDensity('spacious')}
          style={{ fontSize: 13, height: 32 }}
        >
          Spacious
        </button>
        <span className="px-2 py-1 rounded bg-blue-200 dark:bg-blue-800 text-blue-900 dark:text-blue-100 font-bold text-sm">{totalPairs}</span>
        <button
          className={`px-3 py-1 rounded border text-xs font-bold transition-all ${density === 'compact' ? 'bg-blue-100 dark:bg-blue-900 border-blue-400 text-blue-700 dark:text-blue-200' : 'bg-gray-100 dark:bg-gray-800 border-gray-400 text-gray-700 dark:text-gray-200'}`}
          onClick={() => setDensity('compact')}
          style={{ fontSize: 13, height: 32 }}
        >
          Compact
        </button>
        <button
          className={`px-3 py-2 rounded-full border ml-2 ${darkMode ? 'border-gray-600 bg-gray-900 text-white' : 'border-gray-300 bg-white text-black'}`}
          onClick={() => setSettingsOpen(o => !o ? true : false)}
          title="Grid Settings"
          style={{ fontSize: 13, height: 32 }}
        >
          <span role="img" aria-label="settings">⚙️</span>
        </button>
      </div>
      {/* Settings panel/modal */}
      {settingsOpen && (
        <div ref={settingsRef} className={`absolute right-8 top-20 z-50 w-80 max-h-[60vh] overflow-y-auto p-4 sm:p-4 p-2 rounded-lg shadow-lg border ${darkMode ? 'bg-gray-900 border-gray-700 text-white' : 'bg-white border-gray-200 text-black'}`}>
          <h3 className="font-bold mb-2">Grid Settings</h3>
          <div className="mb-4">
            <label className="block text-sm font-semibold mb-1">Master Font Size</label>
            <input type="range" min="0.7" max="2" step="0.05" value={masterFont} onChange={e => setMasterFont(Number(e.target.value))} className="w-full" />
            <div className="text-xs mt-1">{(masterFont * 100).toFixed(0)}%</div>
          </div>
          <div className="mb-4 flex gap-4">
            <div>
              <label className="block text-sm font-semibold mb-1">Name Font Size</label>
              <div className="flex items-center gap-2">
                <button onClick={() => setNameFont(f => Math.max(0.7, f - 0.1))} className="px-2 py-1 rounded bg-gray-300">-</button>
                <span>{(nameFont * 100).toFixed(0)}%</span>
                <button onClick={() => setNameFont(f => Math.min(2, f + 0.1))} className="px-2 py-1 rounded bg-gray-300">+</button>
              </div>
            </div>
            <div>
              <label className="block text-sm font-semibold mb-1">Info Font Size</label>
              <div className="flex items-center gap-2">
                <button onClick={() => setInfoFont(f => Math.max(0.7, f - 0.1))} className="px-2 py-1 rounded bg-gray-300">-</button>
                <span>{(infoFont * 100).toFixed(0)}%</span>
                <button onClick={() => setInfoFont(f => Math.min(2, f + 0.1))} className="px-2 py-1 rounded bg-gray-300">+</button>
              </div>
            </div>
          </div>
          <div className="mb-4">
            <label className="block text-sm font-semibold mb-1">Recent Trade Notification Window</label>
            <select value={notifWindow} onChange={e => setNotifWindow(Number(e.target.value))} className="w-full px-2 py-1 rounded border bg-white text-black">
              {NOTIF_WINDOWS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
            </select>
          </div>
          <div className="mb-2">
            <label className="block text-sm font-semibold mb-1">Notification Style</label>
            <div className="flex gap-4">
              <label className="flex items-center gap-1 cursor-pointer">
                <input type="radio" checked={notifStyle === 'dot'} onChange={() => setNotifStyle('dot')} />
                <span>Green Dot</span>
              </label>
              <label className="flex items-center gap-1 cursor-pointer">
                <input type="radio" checked={notifStyle === 'flag'} onChange={() => setNotifStyle('flag')} />
                <span>Animated Flag</span>
              </label>
            </div>
          </div>
          {/* Notification size slider */}
          <div className="mb-4">
            <label className="block text-sm font-semibold mb-1">Notification Size</label>
            <input
              type="range"
              min={0.7}
              max={2}
              step={0.05}
              value={notifSize}
              onChange={e => setNotifSize(Number(e.target.value))}
              className="w-full"
            />
            <div className="text-xs mt-1">{(notifSize * 100).toFixed(0)}%</div>
          </div>
          {/* Rank badge size slider */}
          <div className="mb-2">
            <label htmlFor="rank-badge-size" className="block text-sm font-semibold mb-1">Rank Badge Size</label>
            <input
              id="rank-badge-size"
              type="range"
              min="0.7"
              max="1.6"
              step="0.01"
              value={rankBadgeSize}
              onChange={e => setRankBadgeSize(Number(e.target.value))}
              className="w-full"
              style={{ accentColor: '#fbbf24' }}
            />
            <div className="text-xs mt-1">{rankBadgeSize.toFixed(2)}x</div>
          </div>
        </div>
      )}
    </div>
  );
}

function isExistInExchange(t) {
  const v = t.exist_in_exchange ?? t.Exist_in_exchange;
  return v === true || v === "true" || v === 1 || v === "1";
}
const PairStatsGrid = ({ onPairSelect, candleType, interval, trades = [], selectedPair = null, previewMode = false, filterBar, darkMode, groupModeEnabled, selectedGroupPairs = [], setSelectedGroupPairs, showForClubFilter, setShowForClubFilter, onVisiblePairsChange, liveFilter = { true: true, false: true }, ...rest }) => {
  // console.log('PairStatsGrid onPairSelect:', onPairSelect);
  const [search, setSearch] = useState(() => localStorage.getItem('pair_stats_search') || '');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [masterFont, setMasterFont] = useState(() => Number(localStorage.getItem('pair_stats_master_font')) || 1);
  const [nameFont, setNameFont] = useState(() => Number(localStorage.getItem('pair_stats_name_font')) || 1.2);
  const [infoFont, setInfoFont] = useState(() => Number(localStorage.getItem('pair_stats_info_font')) || 1);
  const [notifWindow, setNotifWindow] = useState(() => Number(localStorage.getItem('pair_stats_notif_window')) || 15);
  const [notifStyle, setNotifStyle] = useState(() => localStorage.getItem('pair_stats_notif_style') || 'dot');
  const [signalFilter, setSignalFilter] = useState(() => localStorage.getItem('pair_stats_signal_filter') || 'all');
  const [actionFilter, setActionFilter] = useState(() => localStorage.getItem('pair_stats_action_filter') || 'all');
  const [machineFilter, setMachineFilter] = useState(() => localStorage.getItem('pair_stats_machine_filter') || 'all');
  // Replace reputationMode with a slider for reputation intensity
  const [reputationIntensity, setReputationIntensity] = useState(() => {
    const saved = localStorage.getItem('pair_stats_reputation_intensity');
    return saved !== null ? Number(saved) : 0;
  });
  useEffect(() => {
    localStorage.setItem('pair_stats_reputation_intensity', reputationIntensity);
  }, [reputationIntensity]);
  // Reputation mode: 'perTrade' or 'overall'
  const [reputationMode, setReputationMode] = useState(() => localStorage.getItem('pair_stats_reputation_mode') || 'perTrade');
  useEffect(() => {
    localStorage.setItem('pair_stats_reputation_mode', reputationMode);
  }, [reputationMode]);
  // Add a toggle for reputation mode (on/off)
  const [reputationEnabled, setReputationEnabled] = useState(() => {
    const saved = localStorage.getItem('pair_stats_reputation_enabled');
    // Default to true (ON) if no saved value, or if saved value is 'true'
    return saved === null ? true : saved === 'true';
  });
  useEffect(() => {
    localStorage.setItem('pair_stats_reputation_enabled', reputationEnabled);
  }, [reputationEnabled]);
  const settingsRef = useRef();

  // --- Signal filter state for radio/checkbox and select all ---
  const [selectedSignals, setSelectedSignals] = useState(() => {
    const saved = localStorage.getItem('pair_stats_selected_signals');
    if (saved) return JSON.parse(saved);
    // Default: all true
    const obj = {};
    canonicalSignalKeys.forEach(s => obj[s] = true);
    return obj;
  });
  const [signalRadioMode, setSignalRadioMode] = useState(() => localStorage.getItem('pair_stats_signal_radio_mode') === 'true');
  const [signalToggleAll, setSignalToggleAll] = useState(() => localStorage.getItem('pair_stats_signal_toggle_all') === 'true');
  useEffect(() => {
    localStorage.setItem('pair_stats_selected_signals', JSON.stringify(selectedSignals));
  }, [selectedSignals]);
  useEffect(() => {
    localStorage.setItem('pair_stats_signal_radio_mode', signalRadioMode);
  }, [signalRadioMode]);
  useEffect(() => {
    localStorage.setItem('pair_stats_signal_toggle_all', signalToggleAll);
  }, [signalToggleAll]);
  // --- Signal filter logic ---
  const toggleSignal = (signal) => {
    setSelectedSignals(prev => {
      const updated = { ...prev, [signal]: !prev[signal] };
      localStorage.setItem('pair_stats_selected_signals', JSON.stringify(updated));
      return updated;
    });
  };

  // Fetch machines list from API (like main dashboard)
  const [machines, setMachines] = useState([]);
  useEffect(() => {
    const fetchMachines = async () => {
      try {
        const res = await fetch(api('/api/machines'));
        const data = await res.json();
        setMachines(Array.isArray(data.machines) ? data.machines : []);
      } catch (e) {
        setMachines([]);
      }
    };
    fetchMachines();
  }, []);
  // --- Machine filter state for radio/checkbox and select all ---
  const allMachines = machines;
  const [selectedMachines, setSelectedMachines] = useState(() => {
    const saved = localStorage.getItem('pair_stats_selected_machines');
    if (saved) return JSON.parse(saved);
    // Default: all true
    const obj = {};
          allMachines.forEach(m => obj[m.machineid] = true);
    return obj;
  });
  const [machineRadioMode, setMachineRadioMode] = useState(() => localStorage.getItem('pair_stats_machine_radio_mode') === 'true');
  const [machineToggleAll, setMachineToggleAll] = useState(() => localStorage.getItem('pair_stats_machine_toggle_all') === 'true');
  useEffect(() => {
    localStorage.setItem('pair_stats_selected_machines', JSON.stringify(selectedMachines));
  }, [selectedMachines]);
  useEffect(() => {
    localStorage.setItem('pair_stats_machine_radio_mode', machineRadioMode);
  }, [machineRadioMode]);
  useEffect(() => {
    localStorage.setItem('pair_stats_machine_toggle_all', machineToggleAll);
  }, [machineToggleAll]);
  // --- Machine filter logic ---
  const toggleMachine = (machineId) => {
    setSelectedMachines(prev => {
      const updated = { ...prev, [machineId]: !prev[machineId] };
      localStorage.setItem('pair_stats_selected_machines', JSON.stringify(updated));
      return updated;
    });
  };

  // --- Action filter state for radio/checkbox and select all ---
      const allActions = Array.from(new Set(trades.map(t => t.action).filter(Boolean)));
  const [selectedActions, setSelectedActions] = useState(() => {
    const saved = localStorage.getItem('pair_stats_selected_actions');
    if (saved) return JSON.parse(saved);
    // Default: all true
    const obj = {};
    allActions.forEach(a => obj[a] = true);
    return obj;
  });
  const [actionRadioMode, setActionRadioMode] = useState(() => localStorage.getItem('pair_stats_action_radio_mode') === 'true');
  const [actionToggleAll, setActionToggleAll] = useState(() => localStorage.getItem('pair_stats_action_toggle_all') === 'true');
  useEffect(() => {
    localStorage.setItem('pair_stats_selected_actions', JSON.stringify(selectedActions));
  }, [selectedActions]);
  useEffect(() => {
    localStorage.setItem('pair_stats_action_radio_mode', actionRadioMode);
  }, [actionRadioMode]);
  useEffect(() => {
    localStorage.setItem('pair_stats_action_toggle_all', actionToggleAll);
  }, [actionToggleAll]);
  // --- Action filter logic ---
  const toggleAction = (action) => {
    setSelectedActions(prev => {
      const updated = { ...prev, [action]: !prev[action] };
      localStorage.setItem('pair_stats_selected_actions', JSON.stringify(updated));
      return updated;
    });
  };

  useEffect(() => {
    localStorage.setItem('pair_stats_search', search);
  }, [search]);
  useEffect(() => {
    localStorage.setItem('pair_stats_master_font', masterFont);
  }, [masterFont]);
  useEffect(() => {
    localStorage.setItem('pair_stats_name_font', nameFont);
  }, [nameFont]);
  useEffect(() => {
    localStorage.setItem('pair_stats_info_font', infoFont);
  }, [infoFont]);
  useEffect(() => {
    localStorage.setItem('pair_stats_notif_window', notifWindow);
  }, [notifWindow]);
  useEffect(() => {
    localStorage.setItem('pair_stats_notif_style', notifStyle);
  }, [notifStyle]);
  useEffect(() => {
    localStorage.setItem('pair_stats_signal_filter', signalFilter);
  }, [signalFilter]);
  useEffect(() => {
    localStorage.setItem('pair_stats_action_filter', actionFilter);
  }, [actionFilter]);
  useEffect(() => {
    localStorage.setItem('pair_stats_machine_filter', machineFilter);
  }, [machineFilter]);
  // Notification size state
  const [notifSize, setNotifSize] = useState(() => Number(localStorage.getItem('pair_stats_notif_size')) || 1);
  useEffect(() => {
    localStorage.setItem('pair_stats_notif_size', notifSize);
  }, [notifSize]);

  // Close settings when clicking outside
  useEffect(() => {
    if (!settingsOpen) return;
    function handleClick(e) {
      if (settingsRef.current && !settingsRef.current.contains(e.target)) {
        setSettingsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [settingsOpen]);

  // Helper: filter trades by all selected filters (use SignalFrom and MachineId)
  function filterTrades(trades) {
    return trades.filter(t => {
      // Filter by exist_in_exchange
      const isLive = isExistInExchange(t);
      if (liveFilter.true && liveFilter.false) {
        // Both selected: show all
      } else if (liveFilter.true && !isLive) {
        return false; // Only true selected, but trade is false
      } else if (liveFilter.false && isLive) {
        return false; // Only false selected, but trade is true
      } else if (!liveFilter.true && !liveFilter.false) {
        return false; // Neither selected: show nothing
      }
      // Signal filter
      if (Object.keys(selectedSignals).length && !selectedSignals[t.signalfrom]) return false;
      // Machine filter
      if (Object.keys(selectedMachines).length && !selectedMachines[t.machineid]) return false;
      // Action filter
      if (Object.keys(selectedActions).length && !selectedActions[t.action]) return false;
      return true;
    });
  }
  // Updated getPairStats to use filtered trades
  const getPairStats = (pair, trades) => {
    // Use the pre-filtered trades data (same logic for both preview and main grid)
    const pairTrades = filterTrades(trades.filter(t => t.pair === pair));
    
    const sellCount = pairTrades.filter(t => t.action === 'SELL').length;
    const buyCount = pairTrades.filter(t => t.action === 'BUY').length;
    const hedgeCount = pairTrades.filter(t => {
  const isHedge = t.hedge === true || t.hedge === "true" || t.hedge === 1 || t.hedge === "1" || 
                 (typeof t.hedge === 'string' && parseFloat(t.hedge) > 0);
  return isHedge;
}).length;
    // Running is the sum of running and assigned/assign
    const runningCount = pairTrades.filter(t => t.type === 'running' || t.type === 'assigned' || t.type === 'assign').length;
    const profitClosedCount = pairTrades.filter(t => t.type === 'close' && t.pl_after_comm > 0).length;
    const totalProfitAmount = pairTrades.filter(t => t.pl_after_comm > 0).reduce((sum, t) => sum + (parseFloat(t.pl_after_comm) || 0), 0);
    const totalCount = pairTrades.length;
    
    return {
      sellCount,
      buyCount,
      hedgeCount,
      runningCount,
      profitClosedCount,
      totalProfitAmount,
      totalCount,
    };
  };
  // Updated getHedgePL to use filtered trades (but skip filtering in preview mode)
  function getHedgePL(pair, trades) {
    const hedgeTrades = previewMode
          ? trades.filter(t => {
              const isHedge = t.hedge === true || t.hedge === "true" || t.hedge === 1 || t.hedge === "1" || 
                             (typeof t.hedge === 'string' && parseFloat(t.hedge) > 0);
              return t.pair === pair && isHedge && t.pl_after_comm !== undefined;
            })
    : filterTrades(trades.filter(t => {
        const isHedge = t.hedge === true || t.hedge === "true" || t.hedge === 1 || t.hedge === "1" || 
                       (typeof t.hedge === 'string' && parseFloat(t.hedge) > 0);
        return t.pair === pair && isHedge && t.pl_after_comm !== undefined;
      }));
  return hedgeTrades.reduce((sum, t) => sum + (parseFloat(t.pl_after_comm) || 0), 0);
  }

  // Helper to blend two hex colors by t (0-1)
  function blendHexColors(hex1, hex2, t) {
    // Remove #
    hex1 = hex1.replace('#', '');
    hex2 = hex2.replace('#', '');
    const r1 = parseInt(hex1.substring(0,2), 16), g1 = parseInt(hex1.substring(2,4), 16), b1 = parseInt(hex1.substring(4,6), 16);
    const r2 = parseInt(hex2.substring(0,2), 16), g2 = parseInt(hex2.substring(2,4), 16), b2 = parseInt(hex2.substring(4,6), 16);
    const r = Math.round(r1 + (r2 - r1) * t);
    const g = Math.round(g1 + (g2 - g1) * t);
    const b = Math.round(b1 + (b2 - b1) * t);
    return `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${b.toString(16).padStart(2,'0')}`;
  }
  // Helper to blend two gradients (as arrays of color stops)
  function blendGradients(grad1, grad2, t) {
    // grad1/grad2: [color1, color2]
    return [blendHexColors(grad1[0], grad2[0], t), blendHexColors(grad1[1], grad2[1], t)];
  }
  // Define visually pleasing neutral gradient stops for blending
  const neutralStops = darkMode
    ? ['#232526', '#414345']
    : ['#f3f4f6', '#e0eafc']; // softer, lighter for light mode
  // Parse main color stops from gradient string
  function parseStops(gradient) {
    if (typeof gradient !== 'string') return neutralStops;
    const match = gradient.match(/#([0-9a-fA-F]{6})[^#]+#([0-9a-fA-F]{6})/);
    if (!match) return neutralStops;
    return [`#${match[1]}`, `#${match[2]}`];
  }

      const uniquePairs = Array.from(new Set(trades.map(t => t.pair).filter(Boolean)));
  const pairStats = {};
  uniquePairs.forEach(pair => {
    pairStats[pair] = getPairStats(pair, trades);
  });

  // --- Reputation color logic ---
  // Compute mean per trade and mean overall for each pair (MUST be before any use)
  const pairReputation = uniquePairs.map(pair => {
    const profit = pairStats[pair]?.totalProfitAmount || 0;
    const hedge = getHedgePL(pair, trades) || 0;
    const totalCount = pairStats[pair]?.totalCount || 0;
    const meanOverall = profit + hedge;
    const meanPerTrade = totalCount > 0 ? meanOverall / totalCount : 0;
    // Mean of count: profitCount - lossCount
    const pairTrades = trades.filter(t => t.pair === pair);
    const profitCount = pairTrades.filter(t => t.pl_after_comm > 0).length;
    const lossCount = pairTrades.filter(t => t.pl_after_comm < 0).length;
    const meanCount = profitCount - lossCount;
    return { pair, meanOverall, meanPerTrade, profit, hedge, totalCount, meanCount };
  });
  // Use selected mean for reputation
  const getMean = (item) => reputationMode === 'perTrade' ? item.meanPerTrade : item.meanOverall;
  // Sort by selected mean for reputation coloring
  const sortedByReputation = [...pairReputation].sort((a, b) => getMean(b) - getMean(a));
  // 4 green shades (darkest to lightest)
  const greenShades = [
    'linear-gradient(135deg, #008000 0%, #43e97b 100%)', // darkest green
    'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
    'linear-gradient(135deg, #a8ff78 0%, #78ffd6 100%)',
    'linear-gradient(135deg, #e0eafc 0%, #cfdef3 100%)', // lightest green
  ];
  // 4 red shades (lightest to darkest)
  const redShades = [
    'linear-gradient(135deg, #fbeee6 0%, #f5dcdc 100%)', // lightest red
    'linear-gradient(135deg, #ffd6d6 0%, #ffb3b3 100%)',
    'linear-gradient(135deg, #ffb199 0%, #ff6f61 100%)',
    'linear-gradient(135deg, #ff8a80 0%, #ff5252 100%)', // deepest red
  ];
  // Helper to interpolate between two hex colors (already defined as blendHexColors)
  // Define color endpoints for smooth gradients
  const greenStart = '#008000';   // dark green
  const greenEnd = '#e0eafc';     // light green
  const redStart = '#fbeee6';     // light red
  const redEnd = '#ff5252';       // deep red
  // Map pair to reputation info with smooth gradient
  const reputationMap = {};
  const total = sortedByReputation.length;
  // Find the split index between positive and negative means
  const splitIdx = sortedByReputation.findIndex(item => getMean(item) < 0);
  const posCount = splitIdx === -1 ? total : splitIdx;
  const negCount = total - posCount;
  sortedByReputation.forEach((item, idx) => {
    let cardBg;
    if (getMean(item) >= 0 && posCount > 0) {
      // Green: interpolate only among positive means
      const t = posCount > 1 ? idx / (posCount - 1) : 0;
      cardBg = `linear-gradient(135deg, ${blendHexColors(greenStart, greenEnd, t * 0.7)} 0%, ${blendHexColors(greenStart, greenEnd, t)} 100%)`;
    } else if (getMean(item) < 0 && negCount > 0) {
      // Red: interpolate only among negative means
      const negIdx = idx - posCount;
      const t = negCount > 1 ? negIdx / (negCount - 1) : 0;
      cardBg = `linear-gradient(135deg, ${blendHexColors(redStart, redEnd, t * 0.7)} 0%, ${blendHexColors(redStart, redEnd, t)} 100%)`;
    } else {
      cardBg = darkMode ? 'linear-gradient(135deg, #232526 0%, #414345 100%)' : 'linear-gradient(135deg, #e0eafc 0%, #cfdef3 100%)';
    }
    reputationMap[item.pair] = {
      mean: getMean(item),
      isPositive: getMean(item) >= 0,
      cardBg,
    };
  });

  // Filter pairs by search, signal, action, machine
  const filteredPairs = uniquePairs.filter(pair => {
    if (search && !pair.toLowerCase().includes(search.toLowerCase())) return false;
    // Find trades for this pair
    const pairTrades = trades.filter(t => t.Pair === pair);
    // Signal filter
    if (signalFilter !== 'all') {
      if (signalFilter === 'signal' && !pairTrades.some(t => t.Signal)) return false;
      if (signalFilter === 'radio' && !pairTrades.some(t => t.Radio)) return false;
      if (!['signal', 'radio', 'all'].includes(signalFilter) && !pairTrades.some(t => t.Signal === signalFilter)) return false;
    }
    // Action filter
    if (actionFilter !== 'all' && !pairTrades.some(t => t.action === actionFilter)) return false;
    // Machine filter
    if (machineFilter !== 'all' && !pairTrades.some(t => t.Machine === machineFilter)) return false;
    return true;
  });

  // Per-sort-type order state
  const [sortOption, setSortOption] = useState(() => localStorage.getItem('pair_stats_sort_option') || 'latest');
  const [sortOrders, setSortOrders] = useState(() => {
    const saved = localStorage.getItem('pair_stats_sort_orders');
    if (saved) return JSON.parse(saved);
    return { ...DEFAULT_SORT_ORDERS };
  });
  const sortAsc = sortOrders[sortOption] ?? DEFAULT_SORT_ORDERS[sortOption] ?? true;
  useEffect(() => {
    localStorage.setItem('pair_stats_sort_option', sortOption);
  }, [sortOption]);
  useEffect(() => {
    localStorage.setItem('pair_stats_sort_orders', JSON.stringify(sortOrders));
  }, [sortOrders]);
  // When changing sort type, update to its last-used order
  const handleSortChange = (val) => {
    setSortOption(val);
    // No need to update sortOrders here; sortAsc will update from state
  };
  // When toggling, update only the current sort type
  const handleSortToggle = () => {
    setSortOrders(prev => ({ ...prev, [sortOption]: !sortAsc }));
  };

  // Sort the filtered pairs
  const sortedPairs = [...filteredPairs].sort((a, b) => {
    const statsA = pairStats[a];
    const statsB = pairStats[b];
    switch (sortOption) {
      case 'alpha':
        return sortAsc ? a.localeCompare(b) : b.localeCompare(a);
      case 'hedgeCount':
        return sortAsc ? statsA.hedgeCount - statsB.hedgeCount : statsB.hedgeCount - statsA.hedgeCount;
      case 'profitCount':
        return sortAsc ? statsA.profitClosedCount - statsB.profitClosedCount : statsB.profitClosedCount - statsA.profitClosedCount;
      case 'hedgeAmount':
        // Descending: most negative (largest loss) first
        return sortAsc
          ? getHedgePL(a, trades) - getHedgePL(b, trades)
          : getHedgePL(b, trades) - getHedgePL(a, trades);
      case 'profitAmount':
        return sortAsc ? statsA.totalProfitAmount - statsB.totalProfitAmount : statsB.totalProfitAmount - statsA.totalProfitAmount;
      case 'total':
        // Descending: highest total first
        return sortAsc ? statsA.totalCount - statsB.totalCount : statsB.totalCount - statsA.totalCount;
      case 'latest':
      default: {
        // Sort by most recent running/assigned/assign trade (descending)
        const getLatest = (pair) => {
              const pairTrades = trades.filter(t => t.pair === pair && (t.type === 'running' || t.type === 'assigned' || t.type === 'assign'));
    if (pairTrades.length === 0) return 0;
    return Math.max(...pairTrades.map(t => {
      const timeStr = t.candel_time || t.candle_time;
            if (!timeStr) return 0;
            return new Date(timeStr.replace(' ', 'T') + 'Z').getTime();
          }));
        };
        return sortAsc ? getLatest(a) - getLatest(b) : getLatest(b) - getLatest(a);
      }
      case 'meanPerTrade': {
        const itemA = pairReputation.find(x => x.pair === a);
        const itemB = pairReputation.find(x => x.pair === b);
        return (itemB?.meanPerTrade || 0) - (itemA?.meanPerTrade || 0);
      }
      case 'meanOverall': {
        const itemA = pairReputation.find(x => x.pair === a);
        const itemB = pairReputation.find(x => x.pair === b);
        return (itemB?.meanOverall || 0) - (itemA?.meanOverall || 0);
      }
      case 'meanCount': {
        const itemA = pairReputation.find(x => x.pair === a);
        const itemB = pairReputation.find(x => x.pair === b);
        return (itemB?.meanCount || 0) - (itemA?.meanCount || 0);
      }
    }
  });

  // Add CSS for fade/slide-in animation
  const cardAnimation = {
    animation: 'fadeSlideIn 0.5s cubic-bezier(0.4,0,0.2,1)',
  };

  // Stat text color for contrast (fixed for new rule)
  const statBlue = '#1e3a8a'; // dark blue

  // Density state: 'spacious' or 'compact'
  const [density, setDensity] = useState(() => localStorage.getItem('pair_stats_density') || 'spacious');
  useEffect(() => {
    localStorage.setItem('pair_stats_density', density);
  }, [density]);

  // Rank badge size state
  const [rankBadgeSize, setRankBadgeSize] = useState(() => Number(localStorage.getItem('rank_badge_size')) || 1);
  useEffect(() => {
    localStorage.setItem('rank_badge_size', rankBadgeSize);
  }, [rankBadgeSize]);

  // After sorting the filtered pairs
  useEffect(() => {
    if (typeof onVisiblePairsChange === 'function') {
      onVisiblePairsChange(sortedPairs);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(sortedPairs)]);

  // If in previewMode, render only the selected card, centered and enlarged
  if (previewMode && selectedPair) {
    const pair = selectedPair;
    // Find the card rendering logic for the selected pair
    // (Reuse the same rendering as in the grid, but only for this pair)
    const showNotif = hasRecentTrade(trades, pair, notifWindow);
    const notifCount = countRecentTrades(trades, pair, notifWindow);
    let borderColor = darkMode ? '#444' : '#ddd';
    let cardBg = darkMode ? 'linear-gradient(135deg, #232526 0%, #414345 100%)' : 'linear-gradient(135deg, #e0eafc 0%, #cfdef3 100%)';
    let isGreenCard = false;
    let isRedCard = false;
    let redQuartile = 3;
    if (reputationEnabled && reputationIntensity > 0 && reputationMap[pair]) {
      // Interpolate between neutral and reputation color
      const repBg = reputationMap[pair].cardBg;
      const repStops = parseStops(repBg);
      const blendedStops = blendGradients(neutralStops, repStops, reputationIntensity);
      cardBg = `linear-gradient(135deg, ${blendedStops[0]} 0%, ${blendedStops[1]} 100%)`;
      isGreenCard = reputationMap[pair].isPositive;
      isRedCard = !reputationMap[pair].isPositive;
      redQuartile = reputationMap[pair].bin; // Use bin for redQuartile
      borderColor = isGreenCard ? '#43e97b' : isRedCard ? '#ff5858' : borderColor;
    }
    // Dynamic text color for best contrast with background
    let textColor;
    if (!reputationEnabled) {
      textColor = '#fff';
    } else if (reputationIntensity < 0.27) {
      textColor = '#fff';
    } else {
      textColor = '#000';
    }
    // Profit stat color (green info): green until 30%, white from 30% to 55%, then dark blue
    let profitStatColor;
    if (reputationIntensity <= 0.3) {
      profitStatColor = '#16a34a'; // green
    } else if (reputationIntensity <= 0.55) {
      profitStatColor = '#fff'; // white
    } else {
      profitStatColor = statBlue; // dark blue
    }
    // Find the rank of this pair in sortedByReputation
    const rankIdx = sortedByReputation.findIndex(item => item.pair === pair);
    const rank = rankIdx >= 0 ? rankIdx + 1 : null;
    // Determine if in top/bottom 50% for green/red
    const total = sortedByReputation.length;
    const isTopGreen = isGreenCard && rankIdx < total / 2;
    const isBottomRed = isRedCard && rankIdx >= total / 2;
    // Restore notifFontColor logic
    let notifFontColor = '#bfa100';
    if (reputationEnabled && reputationMap[pair]) {
      notifFontColor = '#000';
      const isGreen = reputationMap[pair].isPositive;
      const isRed = !isGreen;
      if (isGreen && rankIdx < total * 0.25) notifFontColor = '#fff'; // top 25% green
      else if (isRed && rankIdx >= total * 0.75) notifFontColor = '#fff'; // bottom 25% red
    }
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 220 }}>
        {/* --- Preview Mode: Selected Card Only --- */}
        {/* Copy the card rendering logic for the selected pair here */}
        <div
          key={pair}
          className={`relative flex flex-col justify-between rounded shadow transition-all duration-300 break-words group ${density === 'compact' ? 'p-2' : ''}`}
          style={{
            wordBreak: 'break-word',
            overflowWrap: 'break-word',
            minWidth: density === 'compact' ? '140px' : '220px',
            maxWidth: '100%',
            minHeight: density === 'compact' ? `${120 * masterFont * infoFont}px` : `${180 * masterFont * infoFont}px`,
            padding: density === 'compact' ? `${8 * masterFont * infoFont}px` : `${16 * masterFont * infoFont}px`,
            border: `2.5px solid ${borderColor}`,
            background: cardBg,
            color: textColor,
            ...cardAnimation,
            fontSize: density === 'compact' ? `${0.92 * infoFont * masterFont}rem` : undefined,
          }}
          onClick={
            !previewMode
              ? () => {
                  window.open(`/reports/list?pair=${encodeURIComponent(pair)}&interval=${encodeURIComponent(interval)}&type=${encodeURIComponent(candleType)}`, '_blank');
                }
              : undefined
          }
        >
          {/* Hover border and shadow effect */}
          <style>{`
            .group:hover {
              transform: scale(1.08);
              box-shadow: 0 12px 36px 0 rgba(0,0,0,0.22), 0 4px 16px 0 rgba(0,0,0,0.13);
              z-index: 2;
              border-color: ${isGreenCard ? '#43e97b' : isRedCard ? '#ff5252' : '#60a5fa'} !important;
              box-shadow: 0 12px 36px 0 rgba(0,0,0,0.22), 0 4px 16px 0 rgba(0,0,0,0.13), 0 0 0 4px ${isGreenCard ? 'rgba(67,233,123,0.25)' : isRedCard ? 'rgba(255,82,82,0.22)' : 'rgba(96,165,250,0.18)'};
              transition: transform 0.22s cubic-bezier(0.4,0,0.2,1), box-shadow 0.22s cubic-bezier(0.4,0,0.2,1), border-color 0.22s cubic-bezier(0.4,0,0.2,1);
            }
          `}</style>
          {/* Ranking badge as bookmark/ribbon, top-right, with animation sync */}
          {rank && reputationEnabled && (
            <span
              className={`absolute top-0 right-0 z-10 px-3 py-1.5 rounded-bl-xl rounded-tr-lg text-xs font-extrabold shadow-xl border-2 transition-transform duration-200 select-none flex items-center gap-1
                ${rank === 1 ? 'border-yellow-400 bg-gradient-to-r from-yellow-200 via-yellow-100 to-white' : ''}
                ${rank === 2 ? 'border-gray-400 bg-gradient-to-r from-gray-200 via-gray-100 to-white' : ''}
                ${rank === 3 ? 'border-amber-700 bg-gradient-to-r from-amber-200 via-amber-100 to-white' : ''}
                ${rank > 3 ? 'border-white bg-white/60 backdrop-blur-md' : ''}
                ${reputationMode === 'perTrade' ? 'animate-pulse-gold' : ''}
                ${reputationMode === 'overall' ? 'animate-pulse-blue' : ''}
                hover:scale-110`}
              style={{
                letterSpacing: '0.04em',
                boxShadow: '0 4px 24px 0 rgba(0,0,0,0.10), 0 1.5px 4px 0 rgba(0,0,0,0.10)',
                color: rank === 1 ? '#bfa100' : rank === 2 ? '#888' : rank === 3 ? '#a16207' : '#1e293b',
                borderWidth: '2.5px',
                fontFamily: 'Inter, Segoe UI, Arial, sans-serif',
                minWidth: '54px',
                justifyContent: 'center',
                background: rank > 3 ? 'rgba(255,255,255,0.65)' : undefined,
                backdropFilter: rank > 3 ? 'blur(6px)' : undefined,
                fontSize: `${rankBadgeSize}em`,
                padding: `${0.7 * rankBadgeSize}em ${1.1 * rankBadgeSize}em`,
              }}
            >
              {rank === 1 && '🏆'}
              {rank === 2 && '🥈'}
              {rank === 3 && '🥉'}
              <span>#{rank}</span>
            </span>
          )}
          {/* Notification badge/flag with count, now top-left and higher up */}
          {showNotif && notifStyle === 'dot' && (
            <span className="absolute top-0 left-2 flex items-center z-10" style={{transform: 'translateY(-0.35em)'}} title="Recent trade(s)">
              <span
                className="rounded-full animate-pulse border-2 border-white flex items-center justify-center text-xs font-extrabold"
                style={{
                  minWidth: `${1.5 * notifSize}em`,
                  minHeight: `${1.5 * notifSize}em`,
                  width: `${1.5 * notifSize}em`,
                  height: `${1.5 * notifSize}em`,
                  background: '#bfa100', // dark yellow
                  color: notifFontColor,
                  fontWeight: 'bold',
                  fontSize: `${1 * notifSize}em`,
                }}
              >
                {notifCount}
              </span>
            </span>
          )}
          {showNotif && notifStyle === 'flag' && (
            <span className="absolute top-0 left-2 flex items-center z-10 animate-bounce" style={{ fontSize: `${1.5 * notifSize}rem`, transform: 'translateY(-0.35em)' }} title="Recent trade(s)">
              <span style={{ color: '#bfa100', fontWeight: 'bold' }}>🚩</span>
              <span
                className="ml-1 text-xs font-extrabold"
                style={{
                  color: notifFontColor,
                  fontSize: `${1 * notifSize}rem`,
                  fontWeight: 'bold',
                }}
              >
                {notifCount}
              </span>
            </span>
          )}
          <div className="font-bold mb-2 pair-name" style={{ fontSize: `${1.2 * nameFont * masterFont}rem`, wordBreak: 'break-word' }}>{pair}</div>
          {/* Matrix layout for stats */}
          <div
            className="w-full h-full flex flex-col justify-center items-center"
            style={{ flex: 1 }}
          >
            <div
              className="grid grid-cols-4 gap-2 w-full mb-2"
              style={{ fontSize: `${1 * infoFont * masterFont}rem`, lineHeight: 1.4, textAlign: 'center' }}
            >
              <div>Sell</div>
              <div>Buy</div>
              <div>Hedge</div>
              <div>Running</div>
              <div><b>{pairStats[pair]?.sellCount}</b></div>
              <div><b>{pairStats[pair]?.buyCount}</b></div>
              <div><b>{pairStats[pair]?.hedgeCount}</b></div>
              <div><b>{pairStats[pair]?.runningCount}</b></div>
            </div>
            <div
              className="grid grid-cols-4 gap-2 w-full"
              style={{ fontSize: `${1 * infoFont * masterFont}rem`, lineHeight: 1.4, textAlign: 'center' }}
            >
              <div>Closed</div>
              <div>Profit</div>
              <div>Hedge</div>
              <div>Total</div>
              <div><b>{pairStats[pair]?.profitClosedCount}</b></div>
              <div>
                <b
                  style={{
                    color:
                      isGreenCard && isTopGreen && pairStats[pair]?.totalProfitAmount < 0 ? '#fff' :
                      isGreenCard || isRedCard ? profitStatColor :
                      pairStats[pair]?.totalProfitAmount > 0 ? 'limegreen' :
                      pairStats[pair]?.totalProfitAmount < 0 ? 'red' : undefined,
                    fontWeight: isGreenCard || isRedCard ? 'bold' : undefined,
                  }}
                >
                  {pairStats[pair]?.totalProfitAmount > 0
                    ? `+${pairStats[pair]?.totalProfitAmount.toFixed(2)}`
                    : pairStats[pair]?.totalProfitAmount < 0
                    ? `-${Math.abs(pairStats[pair]?.totalProfitAmount).toFixed(2)}`
                    : pairStats[pair]?.totalProfitAmount.toFixed(2)}
                </b>
              </div>
              <div>
                <b style={{
                  color:
                    isRedCard && isBottomRed && getHedgePL(pair, trades) > 0 ? '#fff' :
                    isGreenCard ? 'red' :
                    isRedCard ? (redQuartile === 0 ? statYellow : 'red') :
                    getHedgePL(pair, trades) > 0 ? 'limegreen' :
                    getHedgePL(pair, trades) < 0 ? 'red' : undefined,
                  fontWeight: isGreenCard || isRedCard ? 'bold' : undefined,
                }}>
                  {getHedgePL(pair, trades) > 0 ? `+${getHedgePL(pair, trades).toFixed(2)}` : getHedgePL(pair, trades) < 0 ? `-${Math.abs(getHedgePL(pair, trades)).toFixed(2)}` : getHedgePL(pair, trades).toFixed(2)}
                </b>
              </div>
              <div><b>{pairStats[pair]?.totalCount}</b></div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Add a class to the grid container if a pair is selected (and not in previewMode)
  const gridClass = `grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 ${density === 'compact' ? 'xl:grid-cols-6 gap-2' : 'gap-4'}${selectedPair && !previewMode ? ' grid-faded' : ''}`;

  return (
    <div className={`p-2 sm:p-4 min-h-screen transition-colors duration-300 ${darkMode ? 'bg-black text-white' : 'bg-white text-black'}`}>
      {/* Animated Background */}
      <div
        aria-hidden="true"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          zIndex: 0,
          pointerEvents: 'none',
          opacity: darkMode ? 0.18 : 0.13,
          background: darkMode
            ? 'linear-gradient(120deg, #232526 0%, #414345 50%, #232526 100%)'
            : 'linear-gradient(120deg, #e0eafc 0%, #cfdef3 50%, #e0eafc 100%)',
          backgroundSize: '200% 200%',
          animation: 'moveGradient 16s ease-in-out infinite',
        }}
      />
      {/* Responsive filter bar area with four boxes */}
      <div className="w-full flex flex-wrap gap-4 mb-4 flex-col sm:flex-row">
        {filterBar}
        <ControlsBox
          search={search}
          setSearch={setSearch}
          sortOption={sortOption}
          handleSortChange={handleSortChange}
          sortAsc={sortAsc}
          handleSortToggle={handleSortToggle}
          reputationEnabled={reputationEnabled}
          setReputationEnabled={setReputationEnabled}
          reputationMode={reputationMode}
          setReputationMode={setReputationMode}
          reputationIntensity={reputationIntensity}
          setReputationIntensity={setReputationIntensity}
          density={density}
          setDensity={setDensity}
          totalPairs={sortedPairs.filter(pair => filteredPairs.includes(pair)).length}
          settingsOpen={settingsOpen}
          setSettingsOpen={setSettingsOpen}
          darkMode={darkMode}
          masterFont={masterFont}
          setMasterFont={setMasterFont}
          nameFont={nameFont}
          setNameFont={setNameFont}
          infoFont={infoFont}
          setInfoFont={setInfoFont}
          notifWindow={notifWindow}
          setNotifWindow={setNotifWindow}
          notifStyle={notifStyle}
          setNotifStyle={setNotifStyle}
          notifSize={notifSize}
          setNotifSize={setNotifSize}
          rankBadgeSize={rankBadgeSize}
          setRankBadgeSize={setRankBadgeSize}
          NOTIF_WINDOWS={NOTIF_WINDOWS}
          settingsRef={settingsRef} // <-- pass the ref
          showForClubFilter={showForClubFilter}
          setShowForClubFilter={setShowForClubFilter}
        />
      </div>
      {sortedPairs.length === 0 ? (
        <div className={gridClass} style={{ minHeight: '320px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span style={{ fontSize: 24, fontWeight: 600 }}>No grid available</span>
        </div>
      ) : (
        <div className={gridClass}>
          {sortedPairs.filter(pair => filteredPairs.includes(pair)).map(pair => {
            const showNotif = hasRecentTrade(trades, pair, notifWindow);
            const notifCount = countRecentTrades(trades, pair, notifWindow);
            let borderColor = darkMode ? '#444' : '#ddd';
            let cardBg = darkMode ? 'linear-gradient(135deg, #232526 0%, #414345 100%)' : 'linear-gradient(135deg, #e0eafc 0%, #cfdef3 100%)';
            let isGreenCard = false;
            let isRedCard = false;
            let redQuartile = 3;
            if (reputationEnabled && reputationIntensity > 0 && reputationMap[pair]) {
              // Interpolate between neutral and reputation color
              const repBg = reputationMap[pair].cardBg;
              const repStops = parseStops(repBg);
              const blendedStops = blendGradients(neutralStops, repStops, reputationIntensity);
              cardBg = `linear-gradient(135deg, ${blendedStops[0]} 0%, ${blendedStops[1]} 100%)`;
              isGreenCard = reputationMap[pair].isPositive;
              isRedCard = !reputationMap[pair].isPositive;
              redQuartile = reputationMap[pair].bin; // Use bin for redQuartile
              borderColor = isGreenCard ? '#43e97b' : isRedCard ? '#ff5858' : borderColor;
            }
            // Dynamic text color for best contrast with background
            let textColor;
            if (!reputationEnabled) {
              textColor = '#fff';
            } else if (reputationIntensity < 0.27) {
              textColor = '#fff';
            } else {
              textColor = '#000';
            }
            // Profit stat color (green info): green until 30%, white from 30% to 55%, then dark blue
            let profitStatColor;
            if (reputationIntensity <= 0.3) {
              profitStatColor = '#16a34a'; // green
            } else if (reputationIntensity <= 0.55) {
              profitStatColor = '#fff'; // white
            } else {
              profitStatColor = statBlue; // dark blue
            }
            // Find the rank of this pair in sortedByReputation
            const rankIdx = sortedByReputation.findIndex(item => item.pair === pair);
            const rank = rankIdx >= 0 ? rankIdx + 1 : null;
            // Determine if in top/bottom 50% for green/red
            const total = sortedByReputation.length;
            const isTopGreen = isGreenCard && rankIdx < total / 2;
            const isBottomRed = isRedCard && rankIdx >= total / 2;
            // Restore notifFontColor logic
            let notifFontColor = '#bfa100';
            if (reputationEnabled && reputationMap[pair]) {
              notifFontColor = '#000';
              const isGreen = reputationMap[pair].isPositive;
              const isRed = !isGreen;
              if (isGreen && rankIdx < total * 0.25) notifFontColor = '#fff'; // top 25% green
              else if (isRed && rankIdx >= total * 0.75) notifFontColor = '#fff'; // bottom 25% red
            }
            // Add a class to the selected card for group selection
            const isSelectedForGroup = groupModeEnabled && selectedGroupPairs && selectedGroupPairs.includes(pair);
            const cardClass = `relative flex flex-col justify-between rounded shadow transition-all duration-300 break-words group ${density === 'compact' ? 'p-2' : ''}${isSelectedForGroup ? ' selected-for-group' : ''}`;
            return (
              <div
                key={pair}
                className={cardClass}
                style={{
                  wordBreak: 'break-word',
                  overflowWrap: 'break-word',
                  minWidth: density === 'compact' ? '140px' : '220px',
                  maxWidth: '100%',
                  minHeight: density === 'compact' ? `${120 * masterFont * infoFont}px` : `${180 * masterFont * infoFont}px`,
                  padding: density === 'compact' ? `${8 * masterFont * infoFont}px` : `${16 * masterFont * infoFont}px`,
                  border: `2.5px solid ${borderColor}`,
                  background: cardBg,
                  color: textColor,
                  ...cardAnimation,
                  fontSize: density === 'compact' ? `${0.92 * infoFont * masterFont}rem` : undefined,
                  filter: selectedPair && pair !== selectedPair && !previewMode ? 'blur(2px) brightness(0.7)' : undefined,
                  opacity: selectedPair && pair !== selectedPair && !previewMode ? 0.5 : 1,
                  pointerEvents: selectedPair && pair !== selectedPair && !previewMode ? 'none' : undefined,
                }}
                onClick={() => {
                  if (groupModeEnabled && setSelectedGroupPairs) {
                    setSelectedGroupPairs(prev => {
                      const isSelected = prev.includes(pair);
                      if (isSelected) {
                        return prev.filter(p => p !== pair);
                      } else {
                        return [...prev, pair];
                      }
                    });
                  } else {
                    onPairSelect(pair);
                  }
                }}
              >
                {/* Hover border and shadow effect */}
                <style>{`
                  .group:hover {
                    transform: scale(1.08);
                    box-shadow: 0 12px 36px 0 rgba(0,0,0,0.22), 0 4px 16px 0 rgba(0,0,0,0.13);
                    z-index: 2;
                    border-color: ${isGreenCard ? '#43e97b' : isRedCard ? '#ff5252' : '#60a5fa'} !important;
                    box-shadow: 0 12px 36px 0 rgba(0,0,0,0.22), 0 4px 16px 0 rgba(0,0,0,0.13), 0 0 0 4px ${isGreenCard ? 'rgba(67,233,123,0.25)' : isRedCard ? 'rgba(255,82,82,0.22)' : 'rgba(96,165,250,0.18)'};
                    transition: transform 0.22s cubic-bezier(0.4,0,0.2,1), box-shadow 0.22s cubic-bezier(0.4,0,0.2,1), border-color 0.22s cubic-bezier(0.4,0,0.2,1);
                  }
                  ${groupModeEnabled ? `
                    .group {
                      animation: glitter 1.5s infinite;
                    }
                    .group.selected-for-group {
                      animation: none;
                      transform: scale(1.05);
                      border: 3px solid #f59e0b;
                    }
                  ` : ''}

                  @keyframes glitter {
                    0%, 100% { transform: scale(1); }
                    50% { transform: scale(1.02); }
                  }
                `}</style>
                {/* Ranking badge as bookmark/ribbon, top-right, with animation sync */}
                {rank && reputationEnabled && (
                  <span
                    className={`absolute top-0 right-0 z-10 px-3 py-1.5 rounded-bl-xl rounded-tr-lg text-xs font-extrabold shadow-xl border-2 transition-transform duration-200 select-none flex items-center gap-1
                      ${rank === 1 ? 'border-yellow-400 bg-gradient-to-r from-yellow-200 via-yellow-100 to-white' : ''}
                      ${rank === 2 ? 'border-gray-400 bg-gradient-to-r from-gray-200 via-gray-100 to-white' : ''}
                      ${rank === 3 ? 'border-amber-700 bg-gradient-to-r from-amber-200 via-amber-100 to-white' : ''}
                      ${rank > 3 ? 'border-white bg-white/60 backdrop-blur-md' : ''}
                      ${reputationMode === 'perTrade' ? 'animate-pulse-gold' : ''}
                      ${reputationMode === 'overall' ? 'animate-pulse-blue' : ''}
                      hover:scale-110`}
                    style={{
                      letterSpacing: '0.04em',
                      boxShadow: '0 4px 24px 0 rgba(0,0,0,0.10), 0 1.5px 4px 0 rgba(0,0,0,0.10)',
                      color: rank === 1 ? '#bfa100' : rank === 2 ? '#888' : rank === 3 ? '#a16207' : '#1e293b',
                      borderWidth: '2.5px',
                      fontFamily: 'Inter, Segoe UI, Arial, sans-serif',
                      minWidth: '54px',
                      justifyContent: 'center',
                      background: rank > 3 ? 'rgba(255,255,255,0.65)' : undefined,
                      backdropFilter: rank > 3 ? 'blur(6px)' : undefined,
                      fontSize: `${rankBadgeSize}em`,
                      padding: `${0.7 * rankBadgeSize}em ${1.1 * rankBadgeSize}em`,
                    }}
                  >
                    {rank === 1 && '🏆'}
                    {rank === 2 && '🥈'}
                    {rank === 3 && '🥉'}
                    <span>#{rank}</span>
                  </span>
                )}
                {/* Notification badge/flag with count, now top-left and higher up */}
                {showNotif && notifStyle === 'dot' && (
                  <span className="absolute top-0 left-2 flex items-center z-10" style={{transform: 'translateY(-0.35em)'}} title="Recent trade(s)">
                    <span
                      className="rounded-full animate-pulse border-2 border-white flex items-center justify-center text-xs font-extrabold"
                      style={{
                        minWidth: `${1.5 * notifSize}em`,
                        minHeight: `${1.5 * notifSize}em`,
                        width: `${1.5 * notifSize}em`,
                        height: `${1.5 * notifSize}em`,
                        background: '#bfa100', // dark yellow
                        color: notifFontColor,
                        fontWeight: 'bold',
                        fontSize: `${1 * notifSize}em`,
                      }}
                    >
                      {notifCount}
                    </span>
                  </span>
                )}
                {showNotif && notifStyle === 'flag' && (
                  <span className="absolute top-0 left-2 flex items-center z-10 animate-bounce" style={{ fontSize: `${1.5 * notifSize}rem`, transform: 'translateY(-0.35em)' }} title="Recent trade(s)">
                    <span style={{ color: '#bfa100', fontWeight: 'bold' }}>🚩</span>
                    <span
                      className="ml-1 text-xs font-extrabold"
                      style={{
                        color: notifFontColor,
                        fontSize: `${1 * notifSize}rem`,
                        fontWeight: 'bold',
                      }}
                    >
                      {notifCount}
                    </span>
                  </span>
                )}
                <div className="font-bold mb-2 pair-name" style={{ fontSize: `${1.2 * nameFont * masterFont}rem`, wordBreak: 'break-word' }}>{pair}</div>
                {/* Matrix layout for stats */}
                <div
                  className="w-full h-full flex flex-col justify-center items-center"
                  style={{ flex: 1 }}
                >
                  <div
                    className="grid grid-cols-4 gap-2 w-full mb-2"
                    style={{ fontSize: `${1 * infoFont * masterFont}rem`, lineHeight: 1.4, textAlign: 'center' }}
                  >
                    <div>Sell</div>
                    <div>Buy</div>
                    <div>Hedge</div>
                    <div>Running</div>
                    <div><b>{pairStats[pair]?.sellCount}</b></div>
                    <div><b>{pairStats[pair]?.buyCount}</b></div>
                    <div><b>{pairStats[pair]?.hedgeCount}</b></div>
                    <div><b>{pairStats[pair]?.runningCount}</b></div>
                  </div>
                  <div
                    className="grid grid-cols-4 gap-2 w-full"
                    style={{ fontSize: `${1 * infoFont * masterFont}rem`, lineHeight: 1.4, textAlign: 'center' }}
                  >
                    <div>Closed</div>
                    <div>Profit</div>
                    <div>Hedge</div>
                    <div>Total</div>
                    <div><b>{pairStats[pair]?.profitClosedCount}</b></div>
                    <div>
                      <b
                        style={{
                          color:
                            isGreenCard && isTopGreen && pairStats[pair]?.totalProfitAmount < 0 ? '#fff' :
                            isGreenCard || isRedCard ? profitStatColor :
                            pairStats[pair]?.totalProfitAmount > 0 ? 'limegreen' :
                            pairStats[pair]?.totalProfitAmount < 0 ? 'red' : undefined,
                          fontWeight: isGreenCard || isRedCard ? 'bold' : undefined,
                        }}
                      >
                        {pairStats[pair]?.totalProfitAmount > 0
                          ? `+${pairStats[pair]?.totalProfitAmount.toFixed(2)}`
                          : pairStats[pair]?.totalProfitAmount < 0
                          ? `-${Math.abs(pairStats[pair]?.totalProfitAmount).toFixed(2)}`
                          : pairStats[pair]?.totalProfitAmount.toFixed(2)}
                      </b>
                    </div>
                    <div>
                      <b style={{
                        color:
                          isRedCard && isBottomRed && getHedgePL(pair, trades) > 0 ? '#fff' :
                          isGreenCard ? 'red' :
                          isRedCard ? (redQuartile === 0 ? statYellow : 'red') :
                          getHedgePL(pair, trades) > 0 ? 'limegreen' :
                          getHedgePL(pair, trades) < 0 ? 'red' : undefined,
                        fontWeight: isGreenCard || isRedCard ? 'bold' : undefined,
                      }}>
                        {getHedgePL(pair, trades) > 0 ? `+${getHedgePL(pair, trades).toFixed(2)}` : getHedgePL(pair, trades) < 0 ? `-${Math.abs(getHedgePL(pair, trades)).toFixed(2)}` : getHedgePL(pair, trades).toFixed(2)}
                      </b>
                    </div>
                    <div><b>{pairStats[pair]?.totalCount}</b></div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {/* Add animation styles for .selected and .grid-faded */}
      <style>{`
        .grid-faded > div:not(.selected) {
          transition: filter 0.4s cubic-bezier(0.4,0,0.2,1), opacity 0.4s cubic-bezier(0.4,0,0.2,1);
        }
        .selected {
          z-index: 20;
          transform: scale(1.12) translate(-12vw, -8vh);
          box-shadow: 0 12px 36px 0 rgba(0,0,0,0.22), 0 4px 16px 0 rgba(0,0,0,0.13), 0 0 0 6px #fbbf24cc;
          transition: transform 0.5s cubic-bezier(0.4,0,0.2,1), box-shadow 0.5s cubic-bezier(0.4,0,0.2,1);
        }
      `}</style>
      {/* Dashboard Signature */}
      <div
        style={{
          position: 'fixed',
          right: '1.5rem',
          bottom: '1.2rem',
          zIndex: 20,
          fontSize: '1rem',
          fontWeight: 600,
          color: darkMode ? 'rgba(255,255,255,0.32)' : 'rgba(30,41,59,0.32)',
          letterSpacing: '0.04em',
          pointerEvents: 'none',
          userSelect: 'none',
          fontFamily: 'Inter, Segoe UI, Arial, sans-serif',
          textShadow: darkMode ? '0 1px 4px #0008' : '0 1px 4px #fff8',
        }}
      >
        Crafted by LAB
      </div>
    </div>
  );
};

PairStatsGrid.propTypes = {
  onPairSelect: PropTypes.func.isRequired,
  candleType: PropTypes.string,
  interval: PropTypes.string,
  trades: PropTypes.array,
  selectedPair: PropTypes.string,
  previewMode: PropTypes.bool,
  filterBar: PropTypes.node,
  darkMode: PropTypes.bool,
};

export default PairStatsGrid;