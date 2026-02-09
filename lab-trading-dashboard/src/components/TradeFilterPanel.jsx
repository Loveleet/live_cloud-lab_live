import React from "react";
import moment from "moment";

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

const TradeFilterPanel = ({
  selectedSignals,
  setSelectedSignals,
  selectedMachines,
  setSelectedMachines,
  selectedIntervals,
  setSelectedIntervals,
  selectedActions,
  setSelectedActions,
  fromDate,
  toDate,
  setFromDate,
  setToDate,
  includeMinClose,
  setIncludeMinClose,
  signalRadioMode,
  setSignalRadioMode,
  machineRadioMode,
  setMachineRadioMode,
  intervalRadioMode,
  setIntervalRadioMode,
  actionRadioMode,
  setActionRadioMode,
  liveFilter,
  setLiveFilter,
  liveRadioMode,
  setLiveRadioMode,
  signalToggleAll,
  setSignalToggleAll,
  machineToggleAll,
  setMachineToggleAll,
  machines,
  setDateKey,
  assignedCount,
  dateKey
}) => {
  const toMachineKey = (id) => (id === null || id === undefined ? "" : String(id));
  // --- Helper functions for toggling checkboxes/radios in the copied block ---
  // Only define if not present (for this component scope)
  const toggleSignal = (signal) => {
    setSelectedSignals((prev) => {
      const updated = { ...prev, [signal]: !prev[signal] };
      localStorage.setItem("selectedSignals", JSON.stringify(updated));
      return updated;
    });
  };

  const toggleMachine = (machineId) => {
    const key = toMachineKey(machineId);
    setSelectedMachines((prev) => {
      const updated = { ...prev, [key]: !prev[key] };
      localStorage.setItem("selectedMachines", JSON.stringify(updated));
      return updated;
    });
  };

  const toggleInterval = (interval) => {
    setSelectedIntervals((prev) => {
      const updated = { ...prev, [interval]: !prev[interval] };
      localStorage.setItem("selectedIntervals", JSON.stringify(updated));
      return updated;
    });
  };

  const toggleAction = (action) => {
    setSelectedActions((prev) => {
      const updated = { ...prev, [action]: !prev[action] };
      localStorage.setItem("selectedActions", JSON.stringify(updated));
      return updated;
    });
  };



  return (
    <div className="w-full columns-1 sm:columns-2 md:columns-3 lg:columns-4 xl:columns-5 gap-4">
      {/* Signal Filter Group */}
      <div className="break-inside-avoid mb-4 bg-gradient-to-br from-blue-50 via-white to-blue-100 dark:from-blue-900 dark:via-gray-900 dark:to-blue-950 rounded-2xl shadow-lg border border-blue-200 dark:border-blue-800 p-4 gap-2">
        <div className="flex items-center gap-2 mb-2">
          <span className="block text-xl font-extrabold mb-2 tracking-wide relative group transition-transform duration-200 cursor-pointer text-blue-700 dark:text-blue-200 hover:scale-105">
            <span className="mr-2">📡</span> Signal
            <span className="absolute left-0 bottom-0 w-full h-1 rounded bg-gradient-to-r from-blue-400 via-blue-300 to-blue-500 opacity-70 group-hover:opacity-100 group-hover:scale-x-110 transition-all"></span>
          </span>
          <button
            onClick={() => {
              const toggled = !signalRadioMode;
              setSignalRadioMode(toggled);
              if (toggled) {
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
            }}
            className="bg-blue-200 dark:bg-blue-800 text-blue-900 dark:text-blue-100 px-2 py-1 rounded text-xs font-semibold hover:bg-blue-300 dark:hover:bg-blue-700 focus:ring-2 focus:ring-blue-400 transition-all"
            title="Toggle between radio and checkbox mode"
          >
            {signalRadioMode ? "🔘 Check" : "☑️ Radio"}
          </button>
          {!signalRadioMode && (
            <button
              onClick={() => {
                const newState = {};
                Object.keys(selectedSignals).forEach(key => newState[key] = signalToggleAll);
                setSelectedSignals(newState);
                setSignalToggleAll(!signalToggleAll);
                localStorage.setItem("selectedSignals", JSON.stringify(newState));
              }}
              className={`text-xs font-semibold px-2 py-1 rounded w-fit ml-2 ${
                signalToggleAll
                  ? 'bg-green-200 dark:bg-green-800 text-green-900 dark:text-green-100 hover:bg-green-300 dark:hover:bg-green-700 focus:ring-2 focus:ring-green-400'
                  : 'bg-red-200 dark:bg-red-800 text-red-900 dark:text-red-100 hover:bg-red-300 dark:hover:bg-red-700 focus:ring-2 focus:ring-red-400'
              } transition-all`}
              title="Select or uncheck all signals"
            >
              {signalToggleAll ? "✅ All" : "❌ Uncheck"}
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.keys(selectedSignals).map((signal) => (
            <label key={signal} className="flex items-center space-x-2 bg-white dark:bg-gray-800 rounded px-2 py-1 shadow-sm border border-gray-200 dark:border-gray-700">
              {signalRadioMode ? (
                <input
                  type="radio"
                  name="signalFilterRadio"
                  checked={selectedSignals[signal]}
                  onChange={() => {
                    const updated = {};
                    Object.keys(selectedSignals).forEach((key) => {
                      updated[key] = key === signal;
                    });
                    setSelectedSignals(updated);
                    localStorage.setItem("selectedSignals", JSON.stringify(updated));
                  }}
                  className="form-radio h-5 w-5 text-green-600"
                  style={{ accentColor: '#22c55e' }}
                />
              ) : (
                <input
                  type="checkbox"
                  checked={selectedSignals[signal]}
                  onChange={() => toggleSignal(signal)}
                  className="form-checkbox h-5 w-5 text-blue-600"
                />
              )}
              <span className="text-gray-700 dark:text-gray-200 font-semibold">{signalLabels[signal] || signal}</span>
            </label>
          ))}
        </div>
      </div>
      {/* Machine Filter Group */}
      <div className="break-inside-avoid mb-4 bg-gradient-to-br from-green-50 via-white to-green-100 dark:from-green-900 dark:via-gray-900 dark:to-green-950 rounded-2xl shadow-lg border border-green-200 dark:border-green-800 p-4 gap-2">
        <div className="flex items-center gap-2 mb-2">
          <span className="block text-xl font-extrabold mb-2 tracking-wide relative group transition-transform duration-200 cursor-pointer text-green-700 dark:text-green-200 hover:scale-105">
            <span className="mr-2">🖥️</span> Machine
            <span className="absolute left-0 bottom-0 w-full h-1 rounded bg-gradient-to-r from-green-400 via-green-300 to-green-500 opacity-70 group-hover:opacity-100 group-hover:scale-x-110 transition-all"></span>
          </span>
          <button
            onClick={() => {
              const toggled = !machineRadioMode;
              setMachineRadioMode(toggled);
              if (toggled) {
                const selected = machines.find((m) => selectedMachines[toMachineKey(m.machineid)]);
                if (selected) {
                  const updated = {};
                  machines.forEach((m) => {
                    const key = toMachineKey(m.machineid);
                    updated[key] = key === toMachineKey(selected.machineid);
                  });
                  setSelectedMachines(updated);
                  localStorage.setItem("selectedMachines", JSON.stringify(updated));
                }
              }
            }}
            className="bg-green-200 dark:bg-green-800 text-green-900 dark:text-green-100 px-2 py-1 rounded text-xs font-semibold hover:bg-green-300 dark:hover:bg-green-700 focus:ring-2 focus:ring-green-400 transition-all"
            title="Toggle between radio and checkbox mode"
          >
            {machineRadioMode ? "🔘 Check " : "☑️ Radio"}
          </button>
          {!machineRadioMode && (
            <button
              onClick={() => {
                const allChecked = Object.values(selectedMachines).every(v => v === true);
                const updated = {};
                machines.forEach(machine => {
                  const key = toMachineKey(machine.machineid);
                  updated[key] = !allChecked;
                });
                setSelectedMachines(updated);
                setMachineToggleAll(!allChecked);
                localStorage.setItem("selectedMachines", JSON.stringify(updated));
              }}
              className={`text-xs font-semibold px-2 py-1 rounded w-fit ml-2 ${
                Object.values(selectedMachines).every(v => v === false)
                  ? 'bg-green-200 dark:bg-green-800 text-green-900 dark:text-green-100 hover:bg-green-300 dark:hover:bg-green-700 focus:ring-2 focus:ring-green-400'
                  : 'bg-red-200 dark:bg-red-800 text-red-900 dark:text-red-100 hover:bg-red-300 dark:hover:bg-red-700 focus:ring-2 focus:ring-red-400'
              } transition-all`}
              title="Select or uncheck all machines"
            >
              {Object.values(selectedMachines).every(v => v === false) ? "✅ All" : "❌ Uncheck"}
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {machines
            .map((machine) => (
              <label key={machine.machineid} className="flex items-center space-x-2 bg-white dark:bg-gray-800 rounded px-2 py-1 shadow-sm border border-gray-200 dark:border-gray-700">
                {machineRadioMode ? (
                  <input
                    type="radio"
                    name="machineRadio"
                    checked={selectedMachines[toMachineKey(machine.machineid)] === true}
                    onChange={() => {
                      const updated = {};
                      machines.forEach((m) => {
                        const key = toMachineKey(m.machineid);
                        updated[key] = key === toMachineKey(machine.machineid);
                      });
                      setSelectedMachines(updated);
                      localStorage.setItem("selectedMachines", JSON.stringify(updated));
                    }}
                    className="form-radio h-5 w-5 text-green-600"
                    style={{ accentColor: '#22c55e' }}
                  />
                ) : (
                  <input
                    type="checkbox"
                    checked={selectedMachines[toMachineKey(machine.machineid)] || false}
                    onChange={() => toggleMachine(toMachineKey(machine.machineid))}
                    className="form-checkbox h-5 w-5 text-blue-600"
                  />
                )}
                <span className="text-gray-700 dark:text-gray-200 font-semibold">
                  {machine.machineid}
                  {!machine.active && <span className="ml-1 text-xs text-red-500">(inactive)</span>}
                </span>
              </label>
            ))}
        </div>
      </div>
      {/* Interval Filter Group */}
      <div className="break-inside-avoid mb-4 bg-gradient-to-br from-purple-50 via-white to-purple-100 dark:from-purple-900 dark:via-gray-900 dark:to-purple-950 rounded-2xl shadow-lg border border-purple-200 dark:border-purple-800 p-4 gap-2">
        <div className="flex items-center gap-2 mb-2">
          <span className="block text-xl font-extrabold mb-2 tracking-wide relative group transition-transform duration-200 cursor-pointer text-purple-700 dark:text-purple-200 hover:scale-105">
            <span className="mr-2">⏱️</span> Interval
            <span className="absolute left-0 bottom-0 w-full h-1 rounded bg-gradient-to-r from-purple-400 via-purple-300 to-purple-500 opacity-70 group-hover:opacity-100 group-hover:scale-x-110 transition-all"></span>
          </span>
          <button
            onClick={() => {
              const toggled = !intervalRadioMode;
              setIntervalRadioMode(toggled);
              if (toggled) {
                const selected = Object.keys(selectedIntervals).find((key) => selectedIntervals[key]);
                if (selected) {
                  const updated = {};
                  Object.keys(selectedIntervals).forEach((key) => {
                    updated[key] = key === selected;
                  });
                  setSelectedIntervals(updated);
                  localStorage.setItem("selectedIntervals", JSON.stringify(updated));
                }
              }
            }}
            className="bg-purple-200 dark:bg-purple-800 text-purple-900 dark:text-purple-100 px-2 py-1 rounded text-xs font-semibold hover:bg-purple-300 dark:hover:bg-purple-700 focus:ring-2 focus:ring-purple-400 transition-all"
            title="Toggle between radio and checkbox mode"
          >
            {intervalRadioMode ? "🔘 Check" : "☑️ Radio"}
          </button>
          {!intervalRadioMode && (
            <button
              onClick={() => {
                const allSelected = Object.values(selectedIntervals).every(val => val);
                const updated = {};
                Object.keys(selectedIntervals).forEach(key => {
                  updated[key] = !allSelected;
                });
                setSelectedIntervals(updated);
                localStorage.setItem("selectedIntervals", JSON.stringify(updated));
              }}
              className={`text-xs font-semibold px-2 py-1 rounded w-fit ml-2 ${
                Object.values(selectedIntervals).every(val => !val)
                  ? 'bg-green-200 dark:bg-green-800 text-green-900 dark:text-green-100 hover:bg-green-300 dark:hover:bg-green-700 focus:ring-2 focus:ring-green-400'
                  : 'bg-red-200 dark:bg-red-800 text-red-900 dark:text-red-100 hover:bg-red-300 dark:hover:bg-red-700 focus:ring-2 focus:ring-red-400'
              } transition-all`}
              title="Select or uncheck all intervals"
            >
              {Object.values(selectedIntervals).every(val => !val) ? "✅ All" : "❌ Uncheck"}
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.keys(selectedIntervals).map((interval) => (
            <label key={interval} className="flex items-center space-x-2 bg-white dark:bg-gray-800 rounded px-2 py-1 shadow-sm border border-gray-200 dark:border-gray-700">
              {intervalRadioMode ? (
                <input
                  type="radio"
                  name="intervalFilterRadio"
                  checked={selectedIntervals[interval]}
                  onChange={() => {
                    const updated = {};
                    Object.keys(selectedIntervals).forEach((key) => {
                      updated[key] = key === interval;
                    });
                    setSelectedIntervals(updated);
                    localStorage.setItem("selectedIntervals", JSON.stringify(updated));
                  }}
                  className="form-radio h-5 w-5 text-green-600"
                  style={{ accentColor: '#22c55e' }}
                />
              ) : (
                <input
                  type="checkbox"
                  checked={selectedIntervals[interval]}
                  onChange={() => toggleInterval(interval)}
                  className="form-checkbox h-5 w-5 text-blue-600"
                />
              )}
              <span className="text-gray-700 dark:text-gray-200 font-semibold">{interval}</span>
            </label>
          ))}
        </div>
      </div>
      {/* Action Filter Group */}
      <div className="break-inside-avoid mb-4 bg-gradient-to-br from-pink-50 via-white to-pink-100 dark:from-pink-900 dark:via-gray-900 dark:to-pink-950 rounded-2xl shadow-lg border border-pink-200 dark:border-pink-800 p-4 gap-2">
        <div className="flex items-center gap-2 mb-2">
          <span className="block text-xl font-extrabold mb-2 tracking-wide relative group transition-transform duration-200 cursor-pointer text-pink-700 dark:text-pink-200 hover:scale-105">
            <span className="mr-2">🛒</span> Action
            <span className="absolute left-0 bottom-0 w-full h-1 rounded bg-gradient-to-r from-pink-400 via-pink-300 to-pink-500 opacity-70 group-hover:opacity-100 group-hover:scale-x-110 transition-all"></span>
          </span>
          <button
            onClick={() => {
              const toggled = !actionRadioMode;
              setActionRadioMode(toggled);
              if (toggled) {
                const selected = Object.keys(selectedActions).find((key) => selectedActions[key]);
                if (selected) {
                  const updated = { BUY: false, SELL: false };
                  updated[selected] = true;
                  setSelectedActions(updated);
                  localStorage.setItem("selectedActions", JSON.stringify(updated));
                }
              }
            }}
            className="bg-pink-200 dark:bg-pink-800 text-pink-900 dark:text-pink-100 px-2 py-1 rounded text-xs font-semibold hover:bg-pink-300 dark:hover:bg-pink-700 focus:ring-2 focus:ring-pink-400 transition-all"
            title="Toggle between radio and checkbox mode"
          >
            {actionRadioMode ? "🔘 Check" : "☑️ Radio"}
          </button>
          {!actionRadioMode && (
            <button
              onClick={() => {
                const allSelected = Object.values(selectedActions).every(val => val);
                const updated = { BUY: !allSelected, SELL: !allSelected };
                setSelectedActions(updated);
                localStorage.setItem("selectedActions", JSON.stringify(updated));
              }}
              className={`text-xs font-semibold px-2 py-1 rounded w-fit ml-2 ${
                Object.values(selectedActions).every(val => !val)
                  ? 'bg-green-200 dark:bg-green-800 text-green-900 dark:text-green-100 hover:bg-green-300 dark:hover:bg-green-700 focus:ring-2 focus:ring-green-400'
                  : 'bg-red-200 dark:bg-red-800 text-red-900 dark:text-red-100 hover:bg-red-300 dark:hover:bg-red-700 focus:ring-2 focus:ring-red-400'
              } transition-all`}
              title="Select or uncheck all actions"
            >
              {Object.values(selectedActions).every(val => !val) ? "✅ All" : "❌ Uncheck"}
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {["BUY", "SELL"].map((action) => (
            <label key={action} className="flex items-center space-x-2 bg-white dark:bg-gray-800 rounded px-2 py-1 shadow-sm border border-gray-200 dark:border-gray-700">
              {actionRadioMode ? (
                <input
                  type="radio"
                  name="actionRadio"
                  checked={selectedActions[action]}
                  onChange={() => {
                    const updated = { BUY: false, SELL: false };
                    updated[action] = true;
                    setSelectedActions(updated);
                    localStorage.setItem("selectedActions", JSON.stringify(updated));
                  }}
                  className="form-radio h-5 w-5 text-green-600"
                  style={{ accentColor: '#22c55e' }}
                />
              ) : (
                <input
                  type="checkbox"
                  checked={selectedActions[action]}
                  onChange={() => toggleAction(action)}
                  className="form-checkbox h-5 w-5 text-blue-600"
                />
              )}
              <span className="text-gray-700 dark:text-gray-200 font-semibold">{action}</span>
            </label>
          ))}
        </div>
      </div>
      {/* Live Filter Group (exist_in_exchange) */}
      <div className="break-inside-avoid mb-4 bg-gradient-to-br from-emerald-50 via-white to-teal-50 dark:from-emerald-900 dark:via-gray-900 dark:to-teal-950 rounded-2xl shadow-lg border border-emerald-200 dark:border-emerald-800 p-4 gap-2">
        <div className="flex items-center gap-2 mb-2">
          <span className="block text-xl font-extrabold mb-2 tracking-wide relative group transition-transform duration-200 cursor-pointer text-emerald-700 dark:text-emerald-200 hover:scale-105">
            <span className="mr-2">📡</span> Live
            <span className="absolute left-0 bottom-0 w-full h-1 rounded bg-gradient-to-r from-emerald-400 via-emerald-300 to-teal-500 opacity-70 group-hover:opacity-100 group-hover:scale-x-110 transition-all"></span>
          </span>
          <button
            onClick={() => {
              const nextRadio = !liveRadioMode;
              setLiveRadioMode?.(nextRadio);
              if (nextRadio) {
                const f = liveFilter ?? { true: true, false: true };
                const selected = f.true ? "true" : "false";
                setLiveFilter?.({ true: selected === "true", false: selected === "false" });
              }
            }}
            className="bg-emerald-200 dark:bg-emerald-800 text-emerald-900 dark:text-emerald-100 px-2 py-1 rounded text-xs font-semibold hover:bg-emerald-300 dark:hover:bg-emerald-700 focus:ring-2 focus:ring-emerald-400 transition-all"
            title="Toggle between radio and checkbox mode"
          >
            {liveRadioMode ? "🔘 Check" : "☑️ Radio"}
          </button>
          {!liveRadioMode && (
            <button
              onClick={() => {
                const f = liveFilter ?? { true: true, false: true };
                const allChecked = f.true && f.false;
                setLiveFilter?.({ true: !allChecked, false: !allChecked });
              }}
              className={`text-xs font-semibold px-2 py-1 rounded w-fit ml-2 ${
                (liveFilter?.true && liveFilter?.false)
                  ? "bg-red-200 dark:bg-red-800 text-red-900 dark:text-red-100 hover:bg-red-300 dark:hover:bg-red-700 focus:ring-2 focus:ring-red-400"
                  : "bg-green-200 dark:bg-green-800 text-green-900 dark:text-green-100 hover:bg-green-300 dark:hover:bg-green-700 focus:ring-2 focus:ring-green-400"
              } transition-all`}
              title="Uncheck or select all"
            >
              {(liveFilter?.true && liveFilter?.false) ? "❌ Uncheck" : "✅ All"}
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <label className="flex items-center space-x-2 bg-white dark:bg-gray-800 rounded px-2 py-1 shadow-sm border border-gray-200 dark:border-gray-700">
            {liveRadioMode ? (
              <input
                type="radio"
                name="liveFilterRadio"
                checked={!!liveFilter?.true}
                onChange={() => setLiveFilter?.({ true: true, false: false })}
                className="form-radio h-5 w-5 text-emerald-600"
                style={{ accentColor: "#10b981" }}
              />
            ) : (
              <input
                type="checkbox"
                checked={liveFilter?.true ?? true}
                onChange={() => setLiveFilter?.(prev => ({ ...prev, true: !prev.true }))}
                className="form-checkbox h-5 w-5 text-emerald-600"
              />
            )}
            <span className="text-gray-700 dark:text-gray-200 font-semibold">True</span>
          </label>
          <label className="flex items-center space-x-2 bg-white dark:bg-gray-800 rounded px-2 py-1 shadow-sm border border-gray-200 dark:border-gray-700">
            {liveRadioMode ? (
              <input
                type="radio"
                name="liveFilterRadio"
                checked={!!liveFilter?.false}
                onChange={() => setLiveFilter?.({ true: false, false: true })}
                className="form-radio h-5 w-5 text-emerald-600"
                style={{ accentColor: "#10b981" }}
              />
            ) : (
              <input
                type="checkbox"
                checked={liveFilter?.false ?? true}
                onChange={() => setLiveFilter?.(prev => ({ ...prev, false: !prev.false }))}
                className="form-checkbox h-5 w-5 text-emerald-600"
              />
            )}
            <span className="text-gray-700 dark:text-gray-200 font-semibold">False</span>
          </label>
        </div>
      </div>
      {/* Date Range and Reset */}
      <div className="break-inside-avoid mb-4 bg-gradient-to-br from-yellow-50 via-white to-yellow-100 dark:from-yellow-900 dark:via-gray-900 dark:to-yellow-950 rounded-2xl shadow-lg border border-yellow-200 dark:border-yellow-800 p-2 gap-1 justify-start items-stretch">
        <div className="flex items-center gap-2 mb-1">
          <span className="block text-xl font-extrabold mb-2 tracking-wide relative group transition-transform duration-200 cursor-pointer text-yellow-700 dark:text-yellow-200 hover:scale-105">
            <span className="mr-2">📅</span> Date & Time
            <span className="absolute left-0 bottom-0 w-full h-1 rounded bg-gradient-to-r from-yellow-400 via-yellow-300 to-yellow-500 opacity-70 group-hover:opacity-100 group-hover:scale-x-110 transition-all"></span>
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex flex-col">
            <label className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-0.5">From</label>
            <input
              type="datetime-local"
              value={fromDate ? moment(fromDate).format('YYYY-MM-DDTHH:mm') : ''}
              onChange={e => {
                const value = e.target.value;
                setFromDate(value ? moment(value) : null);
              }}
              className="border border-gray-300 dark:border-gray-700 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 dark:bg-gray-800 dark:text-white"
              placeholder="From"
            />
          </div>
          <div className="flex flex-col">
            <label className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-0.5">To</label>
            <input
              type="datetime-local"
              value={toDate ? moment(toDate).format('YYYY-MM-DDTHH:mm') : ''}
              onChange={e => {
                const value = e.target.value;
                setToDate(value ? moment(value) : null);
              }}
              className="border border-gray-300 dark:border-gray-700 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 dark:bg-gray-800 dark:text-white"
              placeholder="To"
            />
          </div>
          <button
            type="button"
            onClick={() => {
              setFromDate(null);
              setToDate(null);
              setDateKey(prev => prev + 1);
            }}
            className="bg-yellow-400 dark:bg-yellow-700 text-yellow-900 dark:text-yellow-100 px-2 py-1 rounded mt-1 hover:bg-yellow-500 dark:hover:bg-yellow-800 focus:ring-1 focus:ring-yellow-400 transition-all font-semibold text-xs"
          >
            Reset
          </button>
        </div>
      </div>
    </div>
  );
};

export default TradeFilterPanel;
