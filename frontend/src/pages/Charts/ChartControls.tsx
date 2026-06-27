import { useState, useEffect } from "react";
import { fetchDatasets } from "../../api/client";
import {
  ChevronDown,
  Layers,
  TrendingUp,
  BarChart3,
  Box,
  Target,
  Hash,
} from "lucide-react";
import type { PivotVariant, PivotPeriod } from "./useChartData";

interface Dataset {
  symbol: string;
  timeframe: string;
  count: number;
}

const ALL_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"];
const CANDLE_LIMITS = [100, 250, 500, 1000, 2500];

interface ChartControlsProps {
  symbol: string;
  timeframe: string;
  limit: number;
  showSRZones: boolean;
  minTouches: number;
  showEMA: boolean;
  showSMCZones: boolean;
  showPivots: boolean;
  pivotVariant: PivotVariant;
  pivotPeriod: PivotPeriod;
  showRoundNumbers: boolean;
  emaVisible: Record<string, boolean>;
  onSymbolChange: (s: string) => void;
  onTimeframeChange: (tf: string) => void;
  onLimitChange: (l: number) => void;
  onToggleSRZones: () => void;
  onMinTouchesChange: (v: number) => void;
  onToggleEMA: () => void;
  onToggleSMCZones: () => void;
  onTogglePivots: () => void;
  onPivotVariantChange: (v: PivotVariant) => void;
  onPivotPeriodChange: (p: PivotPeriod) => void;
  onToggleRoundNumbers: () => void;
  onToggleEMALine: (key: string) => void;
}

export default function ChartControls({
  symbol,
  timeframe,
  limit,
  showSRZones,
  minTouches,
  showEMA,
  showSMCZones,
  showPivots,
  pivotVariant,
  pivotPeriod,
  showRoundNumbers,
  emaVisible,
  onSymbolChange,
  onTimeframeChange,
  onLimitChange,
  onToggleSRZones,
  onMinTouchesChange,
  onToggleEMA,
  onToggleSMCZones,
  onTogglePivots,
  onPivotVariantChange,
  onPivotPeriodChange,
  onToggleRoundNumbers,
  onToggleEMALine,
}: ChartControlsProps) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);

  useEffect(() => {
    fetchDatasets()
      .then((d: Dataset[]) => setDatasets(d))
      .catch(console.error);
  }, []);

  // Unique symbols from datasets
  const symbols = [...new Set(datasets.map((d) => d.symbol))].sort();

  // Available timeframes for current symbol
  const availableTimeframes = new Set(
    datasets.filter((d) => d.symbol === symbol).map((d) => d.timeframe),
  );

  // Auto-select first symbol if none set
  useEffect(() => {
    if (!symbol && symbols.length > 0) {
      onSymbolChange(symbols[0]);
    }
  }, [symbol, symbols, onSymbolChange]);

  // Auto-select first available timeframe if current is not available
  useEffect(() => {
    if (
      symbol &&
      availableTimeframes.size > 0 &&
      !availableTimeframes.has(timeframe)
    ) {
      const first = ALL_TIMEFRAMES.find((tf) => availableTimeframes.has(tf));
      if (first) onTimeframeChange(first);
    }
  }, [symbol, timeframe, availableTimeframes, onTimeframeChange]);

  const EMA_KEYS = [
    { key: "ema_9", label: "9", color: "#f59e0b" },
    { key: "ema_21", label: "21", color: "#3b82f6" },
    { key: "ema_50", label: "50", color: "#8b5cf6" },
    { key: "ema_100", label: "100", color: "#ec4899" },
    { key: "ema_200", label: "200", color: "#ef4444" },
  ];

  return (
    <div
      id="chart-controls"
      className="flex flex-wrap items-center gap-3 bg-slate-800/60 backdrop-blur-sm px-5 py-3 border-slate-700/80 border-b"
    >
      {/* Symbol Selector */}
      <div className="relative" id="symbol-selector">
        <select
          value={symbol}
          onChange={(e) => onSymbolChange(e.target.value)}
          className="bg-slate-700/80 hover:bg-slate-700 px-4 py-2 pr-8 border border-slate-600/60 focus:border-emerald-500/60 rounded-lg font-semibold text-sm text-white transition-all cursor-pointer appearance-none focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
        >
          {symbols.length === 0 && <option value="">Loading…</option>}
          {symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <ChevronDown
          size={14}
          className="top-1/2 right-2.5 absolute text-slate-400 -translate-y-1/2 pointer-events-none"
        />
      </div>

      {/* Timeframe Pills */}
      <div
        className="flex border border-slate-600/60 rounded-lg overflow-hidden"
        id="timeframe-pills"
      >
        {ALL_TIMEFRAMES.map((tf) => {
          const available = availableTimeframes.has(tf);
          const active = tf === timeframe;
          return (
            <button
              key={tf}
              onClick={() => available && onTimeframeChange(tf)}
              disabled={!available}
              className={`px-3 py-1.5 text-xs font-semibold transition-all ${
                active
                  ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40"
                  : available
                    ? "text-slate-400 hover:text-white hover:bg-slate-700/60"
                    : "text-slate-600 cursor-not-allowed opacity-40"
              } ${tf !== ALL_TIMEFRAMES[ALL_TIMEFRAMES.length - 1] ? "border-r border-slate-600/60" : ""}`}
              id={`tf-${tf}`}
            >
              {tf.toUpperCase()}
            </button>
          );
        })}
      </div>

      {/* Candle Limit */}
      <div className="relative" id="limit-selector">
        <select
          value={limit}
          onChange={(e) => onLimitChange(Number(e.target.value))}
          className="bg-slate-700/80 hover:bg-slate-700 px-3 py-2 pr-7 border border-slate-600/60 rounded-lg text-slate-300 text-xs transition-all cursor-pointer appearance-none focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
        >
          {CANDLE_LIMITS.map((l) => (
            <option key={l} value={l}>
              {l} candles
            </option>
          ))}
        </select>
        <BarChart3
          size={12}
          className="top-1/2 right-2 absolute text-slate-500 -translate-y-1/2 pointer-events-none"
        />
      </div>

      {/* Divider */}
      <div className="bg-slate-600/60 mx-1 w-px h-6" />

      {/* S/R Zone Toggle */}
      <button
        onClick={onToggleSRZones}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
          showSRZones
            ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30 shadow-[0_0_12px_rgba(16,185,129,0.1)]"
            : "text-slate-400 border-slate-600/60 hover:text-white hover:bg-slate-700/60"
        }`}
        id="toggle-sr-zones"
      >
        <Layers size={13} />
        S/R Zones
      </button>

      {/* Min Touches Stepper (visible when S/R zones are on) */}
      {showSRZones && (
        <div className="flex items-center gap-2" id="touches-stepper">
          <span className="text-[10px] text-slate-500 uppercase tracking-wider">
            Min Touches
          </span>
          <div className="flex border border-slate-600/60 rounded overflow-hidden">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                onClick={() => onMinTouchesChange(n)}
                className={`px-2 py-0.5 text-[11px] font-mono font-semibold transition-all ${
                  minTouches === n
                    ? "bg-emerald-500/25 text-emerald-300"
                    : "text-slate-400 hover:text-white hover:bg-slate-700/60"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Divider */}
      <div className="bg-slate-600/60 mx-1 w-px h-6" />

      {/* Pivot Points Toggle */}
      <button
        onClick={onTogglePivots}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
          showPivots
            ? "bg-purple-500/15 text-purple-400 border-purple-500/30 shadow-[0_0_12px_rgba(168,85,247,0.1)]"
            : "text-slate-400 border-slate-600/60 hover:text-white hover:bg-slate-700/60"
        }`}
        id="toggle-pivots"
      >
        <Target size={13} />
        Pivots
      </button>

      {/* Pivot variant + period (visible when pivots are on) */}
      {showPivots && (
        <div className="flex items-center gap-1.5" id="pivot-options">
          <select
            value={pivotVariant}
            onChange={(e) => onPivotVariantChange(e.target.value as PivotVariant)}
            className="bg-slate-700/80 hover:bg-slate-700 px-2 py-1 border border-slate-600/60 rounded text-slate-300 text-[11px] cursor-pointer appearance-none focus:outline-none"
            title="Pivot variant"
          >
            <option value="camarilla">Camarilla</option>
            <option value="standard">Standard</option>
            <option value="all">All</option>
          </select>
          <select
            value={pivotPeriod}
            onChange={(e) => onPivotPeriodChange(e.target.value as PivotPeriod)}
            className="bg-slate-700/80 hover:bg-slate-700 px-2 py-1 border border-slate-600/60 rounded text-slate-300 text-[11px] cursor-pointer appearance-none focus:outline-none"
            title="Pivot source period"
          >
            <option value="1d">Prev Day</option>
            <option value="1w">Prev Week</option>
          </select>
        </div>
      )}

      {/* Divider */}
      <div className="bg-slate-600/60 mx-1 w-px h-6" />

      {/* Psychological Round-Number Levels Toggle */}
      <button
        onClick={onToggleRoundNumbers}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
          showRoundNumbers
            ? "bg-amber-500/15 text-amber-400 border-amber-500/30 shadow-[0_0_12px_rgba(245,158,11,0.1)]"
            : "text-slate-400 border-slate-600/60 hover:text-white hover:bg-slate-700/60"
        }`}
        id="toggle-round-numbers"
        title="Large-grain psychological price levels (faint lines)"
      >
        <Hash size={13} />
        Psych Levels
      </button>

      {/* Divider */}
      <div className="bg-slate-600/60 mx-1 w-px h-6" />

      {/* SMC Zone Toggle (FVG / OB) */}
      <button
        onClick={onToggleSMCZones}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
          showSMCZones
            ? "bg-cyan-500/15 text-cyan-400 border-cyan-500/30 shadow-[0_0_12px_rgba(6,182,212,0.1)]"
            : "text-slate-400 border-slate-600/60 hover:text-white hover:bg-slate-700/60"
        }`}
        id="toggle-smc-zones"
      >
        <Box size={13} />
        FVG / OB
      </button>

      {/* Divider */}
      <div className="bg-slate-600/60 mx-1 w-px h-6" />

      {/* EMA Toggle */}
      <button
        onClick={onToggleEMA}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
          showEMA
            ? "bg-blue-500/15 text-blue-400 border-blue-500/30 shadow-[0_0_12px_rgba(59,130,246,0.1)]"
            : "text-slate-400 border-slate-600/60 hover:text-white hover:bg-slate-700/60"
        }`}
        id="toggle-ema"
      >
        <TrendingUp size={13} />
        EMA
      </button>

      {/* EMA Period Toggles */}
      {showEMA && (
        <div className="flex gap-1" id="ema-period-toggles">
          {EMA_KEYS.map(({ key, label, color }) => (
            <button
              key={key}
              onClick={() => onToggleEMALine(key)}
              className={`px-2 py-1 rounded text-[10px] font-bold transition-all border ${
                emaVisible[key]
                  ? "border-opacity-50 shadow-sm"
                  : "opacity-30 border-transparent hover:opacity-60"
              }`}
              style={{
                color: emaVisible[key] ? color : "#94a3b8",
                borderColor: emaVisible[key] ? color : "transparent",
                backgroundColor: emaVisible[key] ? `${color}15` : "transparent",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
