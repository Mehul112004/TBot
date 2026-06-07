import { useMemo, useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { createChart, type IChartApi, ColorType, LineType, LineSeries } from 'lightweight-charts';
import type { LoadedBacktestFile } from '../../types/backtestFile';

interface Props {
  files: LoadedBacktestFile[];
  onRemoveFile: (fileId: string) => void;
}

const FILE_COLORS = [
  { line: '#10b981', label: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' },
  { line: '#6366f1', label: 'text-indigo-400', bg: 'bg-indigo-500/10', border: 'border-indigo-500/30' },
  { line: '#f59e0b', label: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30' },
  { line: '#ec4899', label: 'text-pink-400', bg: 'bg-pink-500/10', border: 'border-pink-500/30' },
  { line: '#06b6d4', label: 'text-cyan-400', bg: 'bg-cyan-500/10', border: 'border-cyan-500/30' },
];

// Metric definitions for the comparison table
const METRIC_ROWS: { key: string; label: string; format: (v: number) => string; higherIsBetter: boolean }[] = [
  { key: 'totalTrades', label: 'Total Trades', format: v => v.toLocaleString(), higherIsBetter: true },
  { key: 'totalPnl', label: 'Net PnL', format: v => `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`, higherIsBetter: true },
  { key: 'totalPnlPct', label: 'Return %', format: v => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, higherIsBetter: true },
  { key: 'avgWinRate', label: 'Avg Win Rate', format: v => `${v.toFixed(1)}%`, higherIsBetter: true },
  { key: 'avgSharpe', label: 'Avg Sharpe', format: v => v.toFixed(2), higherIsBetter: true },
  { key: 'avgProfitFactor', label: 'Avg Profit Factor', format: v => v >= 999 ? '∞' : v.toFixed(2), higherIsBetter: true },
  { key: 'profitableRuns', label: 'Profitable Runs', format: v => v.toString(), higherIsBetter: true },
  { key: 'avgMaxDD', label: 'Avg Max DD %', format: v => `${v.toFixed(1)}%`, higherIsBetter: false },
];

interface FileAggregates {
  totalTrades: number;
  totalPnl: number;
  totalPnlPct: number;
  avgWinRate: number;
  avgSharpe: number;
  avgProfitFactor: number;
  profitableRuns: number;
  avgMaxDD: number;
}

function computeAggregates(file: LoadedBacktestFile): FileAggregates {
  const runs = file.file.runs.filter(r => r.status === 'COMPLETED' && r.metrics.total_trades > 0);
  if (runs.length === 0) {
    return { totalTrades: 0, totalPnl: 0, totalPnlPct: 0, avgWinRate: 0, avgSharpe: 0, avgProfitFactor: 0, profitableRuns: 0, avgMaxDD: 0 };
  }
  const totalTrades = runs.reduce((s, r) => s + r.metrics.total_trades, 0);
  const totalPnl = runs.reduce((s, r) => s + r.metrics.total_pnl, 0);
  const totalPnlPct = runs.reduce((s, r) => s + r.metrics.total_pnl_pct, 0);
  const avgWinRate = runs.reduce((s, r) => s + r.metrics.win_rate, 0) / runs.length;
  const avgSharpe = runs.reduce((s, r) => s + r.metrics.sharpe_ratio, 0) / runs.length;
  const pfValues = runs.map(r => r.metrics.profit_factor).filter(v => v < 999);
  const avgProfitFactor = pfValues.length > 0 ? pfValues.reduce((s, v) => s + v, 0) / pfValues.length : 0;
  const profitableRuns = runs.filter(r => r.metrics.total_pnl > 0).length;
  const avgMaxDD = runs.reduce((s, r) => s + r.metrics.max_drawdown_pct, 0) / runs.length;
  return { totalTrades, totalPnl, totalPnlPct, avgWinRate, avgSharpe, avgProfitFactor, profitableRuns, avgMaxDD };
}

export default function ComparePanel({ files, onRemoveFile }: Props) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const fileAggregates = useMemo(() =>
    files.map(f => ({ file: f, agg: computeAggregates(f) })),
    [files]
  );

  // Strategy-level comparison: find strategies present in multiple files
  const strategyComparisons = useMemo(() => {
    // Collect all unique strategy+symbol+timeframe combos
    const keyMap = new Map<string, { label: string; values: { fileId: string; pnl: number; winRate: number; sharpe: number }[] }>();

    for (const f of files) {
      for (const run of f.file.runs) {
        if (run.status !== 'COMPLETED' || run.metrics.total_trades === 0) continue;
        const key = `${run.strategy_name}|${run.symbol}|${run.timeframe}`;
        if (!keyMap.has(key)) {
          keyMap.set(key, { label: `${run.strategy_name} · ${run.symbol} · ${run.timeframe}`, values: [] });
        }
        keyMap.get(key)!.values.push({
          fileId: f.fileId,
          pnl: run.metrics.total_pnl,
          winRate: run.metrics.win_rate,
          sharpe: run.metrics.sharpe_ratio,
        });
      }
    }

    // Only keep combos present in 2+ files
    return [...keyMap.values()].filter(v => v.values.length >= 2);
  }, [files]);

  // Composite equity curve: sum all runs' equity curves per file
  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Check if any file has equity curve data
    const filesWithEquity = files.filter(f =>
      f.isFull && f.file.runs.some(r => r.equity_curve && r.equity_curve.length > 1)
    );

    if (filesWithEquity.length === 0) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#94a3b8',
        fontFamily: "'Inter', -apple-system, sans-serif",
      },
      grid: {
        vertLines: { color: 'rgba(51, 65, 85, 0.3)' },
        horzLines: { color: 'rgba(51, 65, 85, 0.3)' },
      },
      crosshair: {
        vertLine: { color: 'rgba(148, 163, 184, 0.3)', labelBackgroundColor: '#475569' },
        horzLine: { color: 'rgba(148, 163, 184, 0.3)', labelBackgroundColor: '#475569' },
      },
      rightPriceScale: { borderColor: 'rgba(51, 65, 85, 0.6)' },
      timeScale: { borderColor: 'rgba(51, 65, 85, 0.6)', timeVisible: true, secondsVisible: false },
      width: chartContainerRef.current.clientWidth,
      height: 350,
    });

    chartRef.current = chart;

    // For each file, build a composite equity curve by summing all runs
    filesWithEquity.forEach((f, idx) => {
      const color = FILE_COLORS[idx % FILE_COLORS.length];

      // Collect all equity points with their PnL contribution
      const allPoints = new Map<number, number>();
      let baseCapital = 0;

      for (const run of f.file.runs) {
        if (!run.equity_curve || run.equity_curve.length < 2) continue;
        baseCapital += f.file.config.initial_capital;

        for (const pt of run.equity_curve) {
          const ts = Math.floor(new Date(pt.time).getTime() / 1000);
          allPoints.set(ts, (allPoints.get(ts) ?? baseCapital) + (pt.value - f.file.config.initial_capital));
        }
      }

      // If we have no real composite data, use a simple approach:
      // just take the first run with equity data
      if (allPoints.size === 0) return;

      const sorted = [...allPoints.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([ts, val]) => ({
          time: ts as unknown as import('lightweight-charts').UTCTimestamp,
          value: val,
        }));

      // Deduplicate
      const deduped: typeof sorted = [];
      for (const point of sorted) {
        if (deduped.length === 0 || (point.time as unknown as number) > (deduped[deduped.length - 1].time as unknown as number)) {
          deduped.push(point);
        }
      }

      const series = chart.addSeries(LineSeries, {
        color: color.line,
        lineWidth: 2,
        lineType: LineType.Curved,
        priceFormat: {
          type: 'custom',
          formatter: (price: number) => `$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
        },
      });

      series.setData(deduped);
    });

    chart.timeScale().fitContent();

    const observer = new ResizeObserver(() => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    });
    observer.observe(chartContainerRef.current);

    return () => {
      observer.disconnect();
      if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
    };
  }, [files]);

  const hasEquityData = files.some(f =>
    f.isFull && f.file.runs.some(r => r.equity_curve && r.equity_curve.length > 1)
  );

  return (
    <div className="space-y-6">
      {/* File Pills */}
      <div className="flex flex-wrap gap-2">
        {files.map((f, idx) => {
          const color = FILE_COLORS[idx % FILE_COLORS.length];
          return (
            <div
              key={f.fileId}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${color.bg} border ${color.border}`}
            >
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: FILE_COLORS[idx % FILE_COLORS.length].line }} />
              <span className={`text-sm font-medium ${color.label}`}>{f.fileName}</span>
              <span className="text-xs text-slate-500">{f.file.date}</span>
              <span className="text-xs text-slate-600 font-mono">{f.file.last_git_commit_id.substring(0, 7)}</span>
              {files.length > 1 && (
                <button
                  onClick={() => onRemoveFile(f.fileId)}
                  className="p-0.5 rounded text-slate-500 hover:text-red-400 transition"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Side-by-side Metrics Table */}
      <div className="bg-slate-800/30 border border-slate-700 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700">
          <h3 className="text-sm font-semibold text-white">Aggregate Comparison</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/60">
                <th className="px-4 py-2.5 text-left text-xs text-slate-400 font-medium">Metric</th>
                {files.map((f, idx) => (
                  <th key={f.fileId} className="px-4 py-2.5 text-right text-xs font-medium whitespace-nowrap">
                    <span className={FILE_COLORS[idx % FILE_COLORS.length].label}>
                      {f.fileName.replace('.json', '').substring(0, 20)}
                    </span>
                  </th>
                ))}
                {files.length === 2 && (
                  <th className="px-4 py-2.5 text-right text-xs text-slate-400 font-medium">Delta</th>
                )}
              </tr>
            </thead>
            <tbody>
              {METRIC_ROWS.map(metric => {
                const values = fileAggregates.map(fa => fa.agg[metric.key as keyof FileAggregates] as number);
                const bestIdx = metric.higherIsBetter
                  ? values.indexOf(Math.max(...values))
                  : values.indexOf(Math.min(...values));

                return (
                  <tr key={metric.key} className="border-b border-slate-700/30">
                    <td className="px-4 py-2 text-slate-300 text-xs font-medium">{metric.label}</td>
                    {values.map((val, idx) => (
                      <td
                        key={idx}
                        className={`px-4 py-2 text-right text-xs font-semibold ${
                          idx === bestIdx ? 'text-emerald-400' : 'text-slate-300'
                        }`}
                      >
                        {metric.format(val)}
                      </td>
                    ))}
                    {files.length === 2 && (
                      <td className="px-4 py-2 text-right text-xs">
                        {(() => {
                          const delta = values[1] - values[0];
                          const isBetter = metric.higherIsBetter ? delta > 0 : delta < 0;
                          return (
                            <span className={`font-semibold ${isBetter ? 'text-emerald-400' : delta === 0 ? 'text-slate-500' : 'text-red-400'}`}>
                              {delta >= 0 ? '+' : ''}{metric.format(delta)}
                            </span>
                          );
                        })()}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Overlaid Equity Curves */}
      {hasEquityData ? (
        <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white">Equity Curves Overlay</h3>
            <div className="flex items-center gap-3">
              {files.map((f, idx) => (
                <div key={f.fileId} className="flex items-center gap-1.5 text-xs text-slate-400">
                  <div className="w-3 h-0.5 rounded" style={{ backgroundColor: FILE_COLORS[idx % FILE_COLORS.length].line }} />
                  {f.file.date}
                </div>
              ))}
            </div>
          </div>
          <div
            ref={chartContainerRef}
            className="w-full h-[350px] rounded-lg border border-slate-700/60 bg-slate-900/50 overflow-hidden"
          />
        </div>
      ) : (
        <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-6 text-center text-slate-500 text-sm">
          Upload full backtest files (not brief) to compare equity curves
        </div>
      )}

      {/* Strategy-level Comparison */}
      {strategyComparisons.length > 0 && (
        <div className="bg-slate-800/30 border border-slate-700 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700">
            <h3 className="text-sm font-semibold text-white">Strategy-level Comparison</h3>
            <p className="text-xs text-slate-500 mt-0.5">Strategies present in multiple files</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-700/60">
                  <th className="px-3 py-2 text-left text-slate-400 font-medium">Strategy · Symbol · TF</th>
                  {files.map((f, idx) => (
                    <th key={f.fileId} className="px-3 py-2 text-center font-medium" colSpan={3}>
                      <span className={FILE_COLORS[idx % FILE_COLORS.length].label}>
                        {f.file.date}
                      </span>
                      <div className="flex gap-2 mt-0.5 text-[10px] text-slate-500">
                        <span className="flex-1 text-right">PnL</span>
                        <span className="flex-1 text-right">Win%</span>
                        <span className="flex-1 text-right">Sharpe</span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {strategyComparisons.map(comp => (
                  <tr key={comp.label} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                    <td className="px-3 py-2 text-slate-300 font-medium whitespace-nowrap">{comp.label}</td>
                    {files.map((f, idx) => {
                      const val = comp.values.find(v => v.fileId === f.fileId);
                      if (!val) {
                        return (
                          <td key={f.fileId} colSpan={3} className="px-3 py-2 text-center text-slate-600">—</td>
                        );
                      }
                      return (
                        <td key={f.fileId} colSpan={3} className="px-3 py-2">
                          <div className="flex gap-2">
                            <span className={`flex-1 text-right font-semibold ${val.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {val.pnl >= 0 ? '+' : ''}${val.pnl.toFixed(0)}
                            </span>
                            <span className={`flex-1 text-right ${val.winRate >= 50 ? FILE_COLORS[idx % FILE_COLORS.length].label : 'text-slate-400'}`}>
                              {val.winRate.toFixed(1)}%
                            </span>
                            <span className={`flex-1 text-right ${val.sharpe >= 1 ? 'text-emerald-400' : val.sharpe >= 0 ? 'text-amber-400' : 'text-red-400'}`}>
                              {val.sharpe.toFixed(2)}
                            </span>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
