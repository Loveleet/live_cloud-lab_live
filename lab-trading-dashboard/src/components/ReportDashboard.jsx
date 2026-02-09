import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import PairStatsGrid from './PairStatsGrid';
import PairStatsFilters from './PairStatsFilters';
import Sidebar from './Sidebar';
import RefreshControls from './RefreshControls';
import { api } from '../config';

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
// Animated SVG background for LAB title (copied from main dashboard)
function AnimatedGraphBackground({ width = 400, height = 80, opacity = 0.4 }) {
  const [points1, setPoints1] = useState([]);
  const [points2, setPoints2] = useState([]);
  const tRef = useRef(0);
  const basePoints = [0, 40, 80, 120, 160, 200, 240, 280, 320, 360, 400];
  useEffect(() => {
    let frame;
    function animate() {
      tRef.current += 0.008;
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
      <polyline points={points1.join(' ')} stroke="green" strokeWidth="4" fill="none" strokeLinejoin="round" />
      <polyline points={points2.join(' ')} stroke="red" strokeWidth="4" fill="none" strokeLinejoin="round" />
    </svg>
  );
}
// Placeholder for ListViewComponent
const ListViewComponent = ({ pair, candleType, interval, onBack, gridPreview, onIntervalChange, onCandleTypeChange }) => (
  <div style={{ padding: 32, minHeight: '100vh', position: 'relative' }}>
    {/* Grid preview in top left */}
    <div style={{ position: 'absolute', top: 24, left: 24, zIndex: 10, minWidth: 220, minHeight: 180 }}>
      {gridPreview}
    </div>
    <button onClick={onBack} style={{ marginBottom: 16, position: 'absolute', top: 24, right: 32, zIndex: 20 }}>Back</button>
    <div style={{ marginLeft: 220, marginBottom: 24, display: 'flex', alignItems: 'center', gap: 24 }}>
      <h2 style={{ fontSize: 28, fontWeight: 700, margin: 0 }}>{pair}</h2>
      <label style={{ fontWeight: 500 }}>
        Interval:
        <select value={interval} onChange={e => onIntervalChange(e.target.value)} style={{ marginLeft: 8, padding: 4 }}>
          <option value="1m">1m</option>
          <option value="3m">3m</option>
          <option value="5m">5m</option>
          <option value="15m">15m</option>
          <option value="30m">30m</option>
          <option value="1h">1h</option>
          <option value="4h">4h</option>
        </select>
      </label>
      <label style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}>
        Candle Type:
        <button
          onClick={() => onCandleTypeChange(candleType === 'Regular' ? 'Heiken' : 'Regular')}
          style={{ marginLeft: 8, padding: '4px 12px', borderRadius: 6, border: '1px solid #ccc', background: '#f3f4f6', fontWeight: 600 }}
        >
          {candleType}
        </button>
      </label>
    </div>
    <h3 style={{ marginLeft: 220, fontSize: 18, fontWeight: 400, color: '#444' }}>
      {pair} ({candleType}, {interval})
    </h3>
    {/* TODO: Implement list view details */}
  </div>
);

const ReportDashboard = () => {
  const navigate = useNavigate();
  // Move darkMode state to the top to ensure it is initialized before any usage
  const [darkMode, setDarkMode] = useState(() => {
    if (typeof window !== 'undefined') {
      const theme = localStorage.getItem('pair_stats_theme');
      if (theme) return theme === 'dark';
      return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    }
    return false;
  });
  const [candleType, setCandleType] = useState('Regular');
  const [interval, setInterval] = useState('15m');
  const [trades, setTrades] = useState([]);
  const [symbols, setSymbols] = useState([]); // <-- Add state for unique symbols

  // State for group selection feature
  const [groupModeEnabled, setGroupModeEnabled] = useState(false);
  const [selectedGroupPairs, setSelectedGroupPairs] = useState([]);
  // Add state for showForClubFilter
  const [showForClubFilter, setShowForClubFilter] = useState('All');
  const [visiblePairs, setVisiblePairs] = useState([]); // <-- Add this state


  // Filter state and logic (moved from PairStatsGrid)
  const canonicalSignalKeys = [
    "2POLE_IN5LOOP", "IMACD", "2POLE_Direct_Signal", "HIGHEST SWING HIGH", "LOWEST SWING LOW", "NORMAL SWING HIGH", "NORMAL SWING LOW", "ProGap", "CrossOver", "Spike", "Kicker"
  ];
  const [selectedSignals, setSelectedSignals] = useState(() => {
    const saved = localStorage.getItem('pair_stats_selected_signals');
    if (saved) return JSON.parse(saved);
    const obj = {};
    canonicalSignalKeys.forEach(s => obj[s] = true);
    return obj;
  });
  const [signalRadioMode, setSignalRadioMode] = useState(() => localStorage.getItem('pair_stats_signal_radio_mode') === 'true');
  const [signalToggleAll, setSignalToggleAll] = useState(() => localStorage.getItem('pair_stats_signal_toggle_all') === 'true');

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
  const allMachines = machines;
  const [selectedMachines, setSelectedMachines] = useState(() => {
    const saved = localStorage.getItem('pair_stats_selected_machines');
    if (saved) return JSON.parse(saved);
    const obj = {};
          allMachines.forEach(m => obj[m.machineid] = true);
    return obj;
  });
  const [machineRadioMode, setMachineRadioMode] = useState(() => localStorage.getItem('pair_stats_machine_radio_mode') === 'true');
  const [machineToggleAll, setMachineToggleAll] = useState(() => localStorage.getItem('pair_stats_machine_toggle_all') === 'true');

  const [selectedActions, setSelectedActions] = useState(() => {
    const saved = localStorage.getItem('pair_stats_selected_actions');
    if (saved) return JSON.parse(saved);
    return { BUY: true, SELL: true };
  });
  const [actionRadioMode, setActionRadioMode] = useState(() => localStorage.getItem('pair_stats_action_radio_mode') === 'true');
  const [actionToggleAll, setActionToggleAll] = useState(() => localStorage.getItem('pair_stats_action_toggle_all') === 'true');
  const [liveFilter, setLiveFilter] = useState(() => {
    const saved = localStorage.getItem('pair_stats_live_filter');
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch {
        return { true: true, false: true };
      }
    }
    return { true: true, false: true };
  });
  useEffect(() => {
    localStorage.setItem('pair_stats_live_filter', JSON.stringify(liveFilter));
  }, [liveFilter]);
  const [liveRadioMode, setLiveRadioMode] = useState(() => localStorage.getItem('pair_stats_live_radio_mode') === 'true');
  useEffect(() => {
    localStorage.setItem('pair_stats_live_radio_mode', liveRadioMode ? 'true' : 'false');
  }, [liveRadioMode]);

  // Fetch trades data
  useEffect(() => {
    fetch(api('/api/trades'))
      .then(res => res.json())
      .then(data => {
        const allTrades = Array.isArray(data.trades) ? data.trades : [];
        setTrades(allTrades);
        // Extract unique symbols from trades
        const uniqueSymbols = [...new Set(allTrades.map(t => t.pair).filter(Boolean))];
        setSymbols(uniqueSymbols);
      })
      .catch(() => {
        setTrades([]);
        setSymbols([]);
      });
  }, []);

  // Manual refresh handler combines both data sources
  const refreshReportData = async () => {
    try {
      const [machinesRes, tradesRes] = await Promise.all([
                  fetch(api('/api/machines')),
        fetch(api('/api/trades')),
      ]);
      const machinesJson = machinesRes.ok ? await machinesRes.json() : { machines: [] };
      const tradesJson = tradesRes.ok ? await tradesRes.json() : { trades: [] };
      const machinesList = Array.isArray(machinesJson.machines) ? machinesJson.machines : [];
      const allTrades = Array.isArray(tradesJson.trades) ? tradesJson.trades : [];
      setMachines(machinesList);
      setTrades(allTrades);
      const uniqueSymbols = [...new Set(allTrades.map(t => t.pair).filter(Boolean))];
      setSymbols(uniqueSymbols);
    } catch (e) {
      // keep previous state on error
    }
  };

  useEffect(() => {
    // Debug: log unique symbols and their count
    if (symbols.length > 0) {
      console.log('Unique symbols in dashboard:', symbols, 'Count:', symbols.length);
    }
  }, [symbols]);

  // 1. Apply all filters (signal, machine, action, live/exist_in_exchange)
  function filterTrades(trades) {
    return trades.filter(t => {
      const v = t.exist_in_exchange ?? t.Exist_in_exchange;
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
      if (Object.keys(selectedSignals).length && !selectedSignals[t.signalfrom]) return false;
      if (Object.keys(selectedMachines).length && !selectedMachines[t.machineid]) return false;
      if (Object.keys(selectedActions).length && !selectedActions[t.action]) return false;
      return true;
    });
  }
  const fullyFilteredTrades = filterTrades(trades);

  // 2. Apply the stat/club filter
  function filterTradesByStat(trades, stat) {
    if (stat === 'All') return trades;
    switch (stat) {
      case 'Total Closed Stats':
        return trades.filter(t => t.type === "close" || t.type === "hedge_close");
      case 'Direct Closed Stats':
        return trades.filter(t => t.type === "close");
      case 'Hedge Closed Stats':
        return trades.filter(t => {
          const isHedge = parseHedge(t.hedge);
          return isHedge && t.type === "hedge_close";
        });
      case 'Total Running Stats':
        return trades.filter(t => t.type === "running" || t.type === "hedge_hold");
      case 'Direct Running Stats':
        return trades.filter(t => {
          const isHedge = parseHedge(t.hedge);
          return (t.type === "running" || t.type === "hedge_hold") && !isHedge;
        });
      case 'Hedge Running Stats':
        return trades.filter(t => {
          const isHedge = parseHedge(t.hedge);
          const isHedge11 = parseBoolean(t.hedge_1_1_bool);
          return !isHedge11 && isHedge && (t.type === "running" || t.type === "hedge_hold");
        });
      case 'Total Stats':
        return trades;
      case 'Buy Sell Stats':
        return trades.filter(t => t.action === "BUY" || t.action === "SELL");
      case 'Hedge on Hold':
        return trades.filter(t => {
          const isHedge = parseHedge(t.hedge);
          const isHedge11 = parseBoolean(t.hedge_1_1_bool);
          return isHedge && isHedge11 && (t.type === "running" || t.type === "hedge_hold");
        });
      default:
        return trades;
    }
  }
  const filteredTradesByStat = filterTradesByStat(fullyFilteredTrades, showForClubFilter);

  // 3. Extract unique symbols for the grid
  const filteredSymbols = [...new Set(filteredTradesByStat.map(t => t.pair).filter(Boolean))];

  useEffect(() => {
    // Debug: log filtered symbols and their count for the selected stat
    if (filteredSymbols.length > 0) {
      console.log('Filtered symbols for', showForClubFilter, ':', filteredSymbols, 'Count:', filteredSymbols.length);
    } else {
      console.log('No symbols for', showForClubFilter);
    }
  }, [filteredSymbols, showForClubFilter]);

  // Handler for selecting a pair from the grid
  const handlePairSelect = (pair) => {
    if (groupModeEnabled) {
      setSelectedGroupPairs(prev => {
        const isSelected = prev.some(p => p === pair);
        if (isSelected) {
          return prev.filter(p => p !== pair);
        } else {
          return [...prev, pair];
        }
      });
    } else {
      // Navigate to ListViewPage as a new route
      navigate(`/reports/list?pair=${encodeURIComponent(pair)}&interval=${encodeURIComponent(interval)}&type=${encodeURIComponent(candleType)}`);
    }
  };

  // Handler for going back to grid view
  const handleBack = () => {
    // setSelectedPair(null); // This line is removed
  };

  // Helper: filter trades by all selected filters (use SignalFrom and MachineId)
  function filterTrades(trades) {
    return trades.filter(t => {
      // Signal filter
      if (Object.keys(selectedSignals).length && !selectedSignals[t.signalfrom]) return false;
      // Machine filter
      if (Object.keys(selectedMachines).length && !selectedMachines[t.machineid]) return false;
      // Action filter
      if (Object.keys(selectedActions).length && !selectedActions[t.action]) return false;
      return true;
    });
  }
  const filteredTrades = filterTrades(trades);

  // Render a preview of the selected card (for List View)
  const gridPreview = null; // Always null as selectedPair is removed

  useEffect(() => {
    if (darkMode) {
      document.body.classList.add('dark');
      localStorage.setItem('pair_stats_theme', 'dark');
    } else {
      document.body.classList.remove('dark');
      localStorage.setItem('pair_stats_theme', 'light');
    }
  }, [darkMode]);

  // Prepare the filter bar as a variable
  const filterBar = (
    <PairStatsFilters
      canonicalSignalKeys={canonicalSignalKeys}
      selectedSignals={selectedSignals}
      setSelectedSignals={setSelectedSignals}
      signalRadioMode={signalRadioMode}
      setSignalRadioMode={setSignalRadioMode}
      signalToggleAll={signalToggleAll}
      setSignalToggleAll={setSignalToggleAll}
      allMachines={allMachines}
      selectedMachines={selectedMachines}
      setSelectedMachines={setSelectedMachines}
      machineRadioMode={machineRadioMode}
      setMachineRadioMode={setMachineRadioMode}
      machineToggleAll={machineToggleAll}
      setMachineToggleAll={setMachineToggleAll}
      selectedActions={selectedActions}
      setSelectedActions={setSelectedActions}
      actionRadioMode={actionRadioMode}
      setActionRadioMode={setActionRadioMode}
      actionToggleAll={actionToggleAll}
      setActionToggleAll={setActionToggleAll}
      liveFilter={liveFilter}
      setLiveFilter={setLiveFilter}
      liveRadioMode={liveRadioMode}
      setLiveRadioMode={setLiveRadioMode}
      trades={trades}
      darkMode={darkMode}
    />
  );

  // Sidebar open/close state (copied from main dashboard)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // Only show grid for filteredSymbols
  const tradesForGrid = filteredTradesByStat.filter(t => filteredSymbols.includes(t.pair));

  return (
    <div style={{ minHeight: '100vh', width: '100vw', position: 'relative', background: darkMode ? '#000' : '#f8fafc', display: 'flex' }}>
      {/* Sidebar on the left */}
      <Sidebar isOpen={isSidebarOpen} toggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)} />
      {/* Main content: LAB header, filters, grid/list */}
      <div style={{ flex: 1, minWidth: 0, marginLeft: isSidebarOpen ? '256px' : '80px', transition: 'margin-left 0.3s', padding: '0 24px' }}>
        {/* LAB header (copied from main dashboard) */}
        <div className="sticky top-0 z-40 flex justify-between items-center border-b border-gray-200 dark:border-gray-700 shadow-sm bg-[#f5f6fa] dark:bg-black" style={{ minHeight: '80px', height: '80px', padding: '0 16px', position: 'relative', overflow: 'hidden' }}>
          {/* Animated background fills the header */}
          <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', zIndex: 0, pointerEvents: 'none' }}>
            <AnimatedGraphBackground width={1600} height={80} opacity={0.4} />
          </div>
          {/* Left: Sidebar toggle (if any) */}
          <div style={{ width: 48, zIndex: 1 }} />
          {/* Center: LAB title */}
          <h1
            className="relative z-10 text-4xl font-extrabold text-center bg-gradient-to-r from-blue-500 via-pink-500 to-yellow-400 bg-clip-text text-transparent drop-shadow-lg tracking-tight animate-pulse"
            style={{ WebkitTextStroke: '1px #222', textShadow: '0 4px 24px rgba(0,0,0,0.18)', margin: 0, zIndex: 1 }}
          >
            LAB
            <span className="block w-16 h-1 mx-auto mt-2 rounded-full bg-gradient-to-r from-blue-400 via-pink-400 to-yellow-300 animate-gradient-x"></span>
          </h1>
          {/* Right: Group controls and dark mode button */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: 0, zIndex: 1 }}>
            <RefreshControls
              onRefresh={refreshReportData}
              storageKey="report_dashboard"
              initialIntervalSec={60}
              initialAutoOn={false}
            />
            <button
              onClick={() => setGroupModeEnabled(g => !g)}
              style={{
                background: groupModeEnabled ? 'linear-gradient(90deg, #22c55e 60%, #16a34a 100%)' : 'linear-gradient(90deg, #e5e7eb 60%, #d1d5db 100%)',
                color: groupModeEnabled ? '#fff' : '#222',
                border: 'none',
                borderRadius: 10,
                padding: '6px 14px',
                fontWeight: 700,
                fontSize: 15,
                cursor: 'pointer',
                marginRight: 4,
                boxShadow: groupModeEnabled ? '0 2px 8px #22c55e44' : '0 1px 2px #8882',
                transition: 'all 0.18s cubic-bezier(.4,2,.6,1)',
                transform: groupModeEnabled ? 'scale(1.04)' : 'scale(1)',
                outline: groupModeEnabled ? '2px solid #22c55e' : 'none',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
              className={groupModeEnabled ? 'animate-pulse' : ''}
              title="Enable/Disable Group Mode"
            >
              <span style={{ fontSize: 18 }}>{groupModeEnabled ? '👥' : '👤'}</span>
              Group Mode
            </button>
            <button
              onClick={() => {
                const visibleSet = new Set(visiblePairs);
                const selectedSet = new Set(selectedGroupPairs);
                const allVisibleSelected = visiblePairs.every(p => selectedSet.has(p));
                if (allVisibleSelected) {
                  // Deselect only visible pairs
                  setSelectedGroupPairs(selectedGroupPairs.filter(p => !visibleSet.has(p)));
                } else {
                  // Add all visible pairs to selection (no duplicates)
                  setSelectedGroupPairs(Array.from(new Set([...selectedGroupPairs, ...visiblePairs])));
                }
              }}
              disabled={!groupModeEnabled}
              style={{
                padding: '6px 14px',
                borderRadius: 10,
                border: 'none',
                background: groupModeEnabled ? '#2563eb' : '#e5e7eb',
                color: groupModeEnabled ? '#fff' : '#888',
                fontWeight: 700,
                fontSize: 15,
                boxShadow: groupModeEnabled ? '0 2px 8px #2563eb44' : '0 1px 2px #8882',
                cursor: groupModeEnabled ? 'pointer' : 'not-allowed',
                opacity: groupModeEnabled ? 1 : 0.6,
                transition: 'all 0.18s cubic-bezier(.4,2,.6,1)',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
              title="Select/Unselect All"
            >
              <span style={{ fontSize: 18 }}>{selectedGroupPairs.length === visiblePairs.length ? '✅' : '☑️'}</span>
              Select All
            </button>
            <button
              onClick={() => {
                const symbols = selectedGroupPairs.join(',');
                navigate(`/pages/group-view?symbols=${encodeURIComponent(symbols)}&interval=${encodeURIComponent(interval)}&type=${encodeURIComponent(candleType)}`);
              }}
              disabled={selectedGroupPairs.length === 0}
              style={{
                padding: '6px 14px',
                borderRadius: 10,
                border: 'none',
                background: selectedGroupPairs.length > 0 ? 'linear-gradient(90deg, #6366f1 60%, #0ea5e9 100%)' : '#e5e7eb',
                color: selectedGroupPairs.length > 0 ? '#fff' : '#888',
                fontWeight: 700,
                fontSize: 15,
                boxShadow: selectedGroupPairs.length > 0 ? '0 2px 8px #6366f144' : '0 1px 2px #8882',
                cursor: selectedGroupPairs.length > 0 ? 'pointer' : 'not-allowed',
                opacity: selectedGroupPairs.length > 0 ? 1 : 0.6,
                transition: 'all 0.18s cubic-bezier(.4,2,.6,1)',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                animation: selectedGroupPairs.length > 0 ? 'pulse 1.2s infinite' : 'none',
              }}
              title="View Selected Group"
            >
              <span style={{ fontSize: 18 }}>➡️</span>
              View in Group ({selectedGroupPairs.length})
            </button>
            {/* Dark/Bright mode toggle button (right side) */}
            <button
              onClick={() => setDarkMode(dm => !dm)}
              className="z-20 p-2 rounded-full bg-white/80 dark:bg-gray-800/80 shadow hover:scale-110 transition-all"
              title={darkMode ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
              style={{ fontSize: 22, marginLeft: 10 }}
            >
              {darkMode ? '🌞' : '🌙'}
            </button>
          </div>
        </div>
        {/* Filter bar, grid/list, etc. */}
            {/* Group Selection Controls */}

            <PairStatsGrid
              key="main-grid"
              onPairSelect={handlePairSelect}
              candleType={candleType}
              interval={interval}
              trades={tradesForGrid}
              selectedPair={null}
              darkMode={darkMode}
              filterBar={filterBar}
              groupModeEnabled={groupModeEnabled}
              selectedGroupPairs={selectedGroupPairs}
              setSelectedGroupPairs={setSelectedGroupPairs}
              showForClubFilter={showForClubFilter}
              setShowForClubFilter={setShowForClubFilter}
              onVisiblePairsChange={setVisiblePairs}
              liveFilter={liveFilter}
            />
      </div>
    </div>
  );
};

export default ReportDashboard; 