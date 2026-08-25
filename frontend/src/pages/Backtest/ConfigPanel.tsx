import { useState, useEffect, useMemo } from "react";
import type { BacktestConfig } from "../../types/backtest";
import type { StrategyInfo } from "../../api/client";
import { fetchSymbols } from "../../api/client";

const TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"];


interface Props {
  strategies: StrategyInfo[];
  onSubmit: (config: BacktestConfig) => void;
  loading: boolean;
}

export default function ConfigPanel({ strategies, onSubmit, loading }: Props) {
  const [symbol, setSymbol] = useState("");
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([]);

  useEffect(() => {
    fetchSymbols("binance")
      .then((symbols) => {
        setAvailableSymbols(symbols);
        if (symbols.length > 0) setSymbol(symbols[0]);
      })
      .catch(() => {
        const fallback = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"];
        setAvailableSymbols(fallback);
        setSymbol(fallback[0]);
      });
  }, []);
  const [timeframe, setTimeframe] = useState("1h");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [capital, setCapital] = useState("10000");
  const [risk, setRisk] = useState("1.0");
  const [costBps, setCostBps] = useState("10.0");
  const [validationError, setValidationError] = useState<string | null>(null);
  const eligibleStrategies = useMemo(
    () => strategies.filter(
      (strategy) => strategy.supports_historical_backtest && strategy.timeframes.includes(timeframe),
    ),
    [strategies, timeframe],
  );

  const toggleStrategy = (name: string) => {
    setSelectedStrategies((prev) =>
      prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name],
    );
  };

  const selectTimeframe = (nextTimeframe: string) => {
    if (nextTimeframe !== timeframe) {
      setSelectedStrategies([]);
      setTimeframe(nextTimeframe);
    }
  };

  const selectAll = () => {
    if (selectedStrategies.length === eligibleStrategies.length) {
      setSelectedStrategies([]);
    } else {
      setSelectedStrategies(eligibleStrategies.map((s) => s.name));
    }
  };

  const handleSubmit = () => {
    setValidationError(null);

    if (!startDate || !endDate) {
      setValidationError("Start and end dates are required");
      return;
    }
    if (new Date(startDate) >= new Date(endDate)) {
      setValidationError("Start date must be before end date");
      return;
    }
    if (selectedStrategies.length === 0) {
      setValidationError("Select at least one strategy");
      return;
    }
    const capNum = parseFloat(capital);
    if (isNaN(capNum) || capNum <= 0) {
      setValidationError("Initial capital must be a positive number");
      return;
    }
    const riskNum = parseFloat(risk);
    if (isNaN(riskNum) || riskNum < 0.1 || riskNum > 100) {
      setValidationError("Risk must be between 0.1% and 100%");
      return;
    }
    const costNum = parseFloat(costBps);
    if (isNaN(costNum) || costNum < 0 || costNum > 100) {
      setValidationError("All-in cost must be between 0 and 100 bps per side");
      return;
    }

    onSubmit({
      symbol,
      timeframe,
      start_date: new Date(startDate).toISOString(),
      end_date: new Date(endDate).toISOString(),
      strategy_names: selectedStrategies,
      initial_capital: capNum,
      risk_per_trade: riskNum,
      slippage_bps: costNum,
    });
  };

  return (
    <div className="space-y-5 p-5" id="backtest-config-panel">
      <h2 className="font-semibold text-slate-300 text-sm uppercase tracking-wider">
        Configuration
      </h2>

      {/* Symbol */}
      <div>
        <label className="block mb-1.5 font-medium text-slate-400 text-xs">
          Symbol
        </label>
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="bg-slate-700 px-3 py-2 border border-slate-600 focus:border-emerald-500 rounded-lg w-full text-sm text-white focus:ring-2 focus:ring-emerald-500/50 outline-none"
          id="backtest-symbol-select"
        >
          {availableSymbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block mb-1.5 font-medium text-slate-400 text-xs">
          All-in execution cost (bps per side)
        </label>
        <input
          type="number"
          value={costBps}
          onChange={(e) => setCostBps(e.target.value)}
          min="0"
          max="100"
          step="0.5"
          className="bg-slate-700 px-3 py-2 border border-slate-600 focus:border-emerald-500 rounded-lg w-full text-sm text-white focus:ring-2 focus:ring-emerald-500/50 outline-none"
          id="backtest-cost-bps"
        />
      </div>

      {/* Timeframe */}
      <div>
        <label className="block mb-1.5 font-medium text-slate-400 text-xs">
          Timeframe
        </label>
        <div className="flex gap-1.5">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => selectTimeframe(tf)}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                timeframe === tf
                  ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                  : "bg-slate-700/50 text-slate-400 border border-slate-600 hover:text-white"
              }`}
              id={`tf-btn-${tf}`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Date Range */}
      <div className="gap-3 grid grid-cols-2">
        <div>
          <label className="block mb-1.5 font-medium text-slate-400 text-xs">
            Start Date
          </label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="bg-slate-700 px-3 py-2 border border-slate-600 focus:border-emerald-500 rounded-lg w-full text-sm text-white focus:ring-2 focus:ring-emerald-500/50 outline-none"
            id="backtest-start-date"
          />
        </div>
        <div>
          <label className="block mb-1.5 font-medium text-slate-400 text-xs">
            End Date
          </label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="bg-slate-700 px-3 py-2 border border-slate-600 focus:border-emerald-500 rounded-lg w-full text-sm text-white focus:ring-2 focus:ring-emerald-500/50 outline-none"
            id="backtest-end-date"
          />
        </div>
      </div>

      {/* Strategies */}
      <div>
        <div className="flex justify-between items-center mb-1.5">
          <label className="font-medium text-slate-400 text-xs">
            Strategies
          </label>
          <button
            onClick={selectAll}
            className="text-emerald-400 text-xs hover:text-emerald-300 transition-colors"
          >
            {selectedStrategies.length === eligibleStrategies.length
              ? "Deselect All"
              : "Select All"}
          </button>
        </div>
        <div className="space-y-1 bg-slate-700/30 p-2 border border-slate-600 rounded-lg max-h-48 overflow-y-auto">
          {eligibleStrategies.map((strat) => (
            <label
              key={strat.name}
              className={`flex items-center gap-2.5 px-2.5 py-2 rounded-md cursor-pointer transition-colors ${
                selectedStrategies.includes(strat.name)
                  ? "bg-emerald-500/10 border border-emerald-500/30"
                  : "border border-transparent hover:bg-slate-700/50"
              }`}
            >
              <input
                type="checkbox"
                checked={selectedStrategies.includes(strat.name)}
                onChange={() => toggleStrategy(strat.name)}
                className="bg-slate-700 border-slate-500 rounded w-3.5 h-3.5 text-emerald-500 focus:ring-emerald-500/50"
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-white truncate">{strat.name}</div>
                <div className="text-slate-500 text-xs truncate">
                  {strat.timeframes.join(", ")}
                </div>
              </div>
            </label>
          ))}
          {eligibleStrategies.length === 0 && (
            <p className="py-4 text-center text-slate-500 text-xs">
              No causal historical strategies support this timeframe
            </p>
          )}
        </div>
      </div>

      {/* Capital & Risk */}
      <div className="gap-3 grid grid-cols-2">
        <div>
          <label className="block mb-1.5 font-medium text-slate-400 text-xs">
            Capital ($)
          </label>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
            min="1"
            step="100"
            className="bg-slate-700 px-3 py-2 border border-slate-600 focus:border-emerald-500 rounded-lg w-full text-sm text-white focus:ring-2 focus:ring-emerald-500/50 outline-none"
            id="backtest-capital"
          />
        </div>
        <div>
          <label className="block mb-1.5 font-medium text-slate-400 text-xs">
            Risk (%)
          </label>
          <input
            type="number"
            value={risk}
            onChange={(e) => setRisk(e.target.value)}
            min="0.1"
            max="100"
            step="0.1"
            className="bg-slate-700 px-3 py-2 border border-slate-600 focus:border-emerald-500 rounded-lg w-full text-sm text-white focus:ring-2 focus:ring-emerald-500/50 outline-none"
            id="backtest-risk"
          />
        </div>
      </div>

      {/* Validation Error */}
      {validationError && (
        <p className="bg-red-500/10 px-3 py-2 border border-red-500/20 rounded-md text-red-400 text-xs">
          {validationError}
        </p>
      )}

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={loading}
        className={`w-full py-2.5 rounded-lg font-medium text-sm transition-all ${
          loading
            ? "bg-slate-600 text-slate-400 cursor-not-allowed"
            : "bg-emerald-600 text-white hover:bg-emerald-500 active:scale-[0.98]"
        }`}
        id="run-backtest-btn"
      >
        {loading ? (
          <span className="flex justify-center items-center gap-2">
            <span className="border-2 border-slate-400/30 border-t-slate-400 rounded-full w-4 h-4 animate-spin" />
            Running...
          </span>
        ) : (
          "▶ Run Backtest"
        )}
      </button>
    </div>
  );
}
