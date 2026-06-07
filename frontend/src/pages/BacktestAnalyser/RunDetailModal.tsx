import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { createChart, type IChartApi, ColorType, LineType, AreaSeries } from 'lightweight-charts';
import type { BacktestFileRun } from '../../types/backtestFile';

interface Props {
  run: BacktestFileRun;
  onClose: () => void;
}

function formatDuration(mins: number): string {
  if (mins < 60) return `${Math.round(mins)}m`;
  if (mins < 1440) return `${(mins / 60).toFixed(1)}h`;
  return `${(mins / 1440).toFixed(1)}d`;
}

function formatPnl(v: number): string {
  const prefix = v >= 0 ? '+' : '';
  return `${prefix}$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function RunDetailModal({ run, onClose }: Props) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const m = run.metrics;
  const hasEquity = run.equity_curve && run.equity_curve.length > 1;
  const hasTrades = run.trades && run.trades.length > 0;

  // Equity curve chart
  useEffect(() => {
    if (!hasEquity || !chartContainerRef.current) return;

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
        vertLine: { color: 'rgba(16, 185, 129, 0.3)', labelBackgroundColor: '#10b981' },
        horzLine: { color: 'rgba(16, 185, 129, 0.3)', labelBackgroundColor: '#10b981' },
      },
      rightPriceScale: { borderColor: 'rgba(51, 65, 85, 0.6)' },
      timeScale: { borderColor: 'rgba(51, 65, 85, 0.6)', timeVisible: true, secondsVisible: false },
      width: chartContainerRef.current.clientWidth,
      height: 280,
    });

    chartRef.current = chart;

    const isPositive = m.total_pnl >= 0;
    const series = chart.addSeries(AreaSeries, {
      topColor: isPositive ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.25)',
      bottomColor: isPositive ? 'rgba(16, 185, 129, 0.02)' : 'rgba(239, 68, 68, 0.02)',
      lineColor: isPositive ? '#10b981' : '#ef4444',
      lineWidth: 2,
      lineType: LineType.Curved,
      priceFormat: {
        type: 'custom',
        formatter: (price: number) => `$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      },
    });

    const chartData = run.equity_curve!
      .map(p => ({
        time: (new Date(p.time).getTime() / 1000) as unknown as import('lightweight-charts').UTCTimestamp,
        value: p.value,
      }))
      .sort((a, b) => (a.time as unknown as number) - (b.time as unknown as number));

    // Deduplicate
    const deduped: typeof chartData = [];
    for (const point of chartData) {
      if (deduped.length === 0 || (point.time as unknown as number) > (deduped[deduped.length - 1].time as unknown as number)) {
        deduped.push(point);
      }
    }

    series.setData(deduped);
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
  }, [run, hasEquity, m.total_pnl]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm" onClick={onClose} />

      {/* Slide-over panel */}
      <div className="relative w-full max-w-2xl bg-slate-900 border-l border-slate-700 overflow-y-auto animate-slide-in">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-slate-900/95 backdrop-blur border-b border-slate-700 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-white">{run.strategy_name}</h2>
            <p className="text-sm text-slate-400 mt-0.5">
              {run.symbol} · {run.timeframe} · {m.total_trades} trades
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition"
          >
            <X size={20} />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <MetricCard label="Win Rate" value={`${m.win_rate.toFixed(1)}%`} color={m.win_rate >= 50 ? 'green' : 'red'} />
            <MetricCard label="Total PnL" value={formatPnl(m.total_pnl)} sub={`${m.total_pnl_pct >= 0 ? '+' : ''}${m.total_pnl_pct.toFixed(2)}%`} color={m.total_pnl >= 0 ? 'green' : 'red'} />
            <MetricCard label="Sharpe" value={m.sharpe_ratio.toFixed(2)} color={m.sharpe_ratio >= 1 ? 'green' : m.sharpe_ratio >= 0 ? 'amber' : 'red'} />
            <MetricCard label="Sortino" value={m.sortino_ratio.toFixed(2)} color={m.sortino_ratio >= 1 ? 'green' : m.sortino_ratio >= 0 ? 'amber' : 'red'} />
            <MetricCard label="Max DD" value={`$${m.max_drawdown.toFixed(0)}`} sub={`${m.max_drawdown_pct.toFixed(1)}%`} color={m.max_drawdown_pct <= 10 ? 'green' : m.max_drawdown_pct <= 25 ? 'amber' : 'red'} />
            <MetricCard label="Avg R/R" value={m.avg_rr.toFixed(2)} color={m.avg_rr >= 1.5 ? 'green' : m.avg_rr >= 1 ? 'amber' : 'red'} />
            <MetricCard label="Profit Factor" value={m.profit_factor >= 999 ? '∞' : m.profit_factor.toFixed(2)} color={m.profit_factor >= 1.5 ? 'green' : m.profit_factor >= 1 ? 'amber' : 'red'} />
            <MetricCard label="Avg Duration" value={formatDuration(m.avg_trade_duration_mins)} color="slate" />
            <MetricCard label="Best / Worst" value={`$${m.best_trade_pnl.toFixed(0)} / $${m.worst_trade_pnl.toFixed(0)}`} color="blue" />
          </div>

          {/* Equity Curve */}
          {hasEquity ? (
            <div>
              <h3 className="text-sm font-semibold text-white mb-2">Equity Curve</h3>
              <div
                ref={chartContainerRef}
                className="w-full h-[280px] rounded-xl border border-slate-700 bg-slate-800/30 overflow-hidden"
              />
            </div>
          ) : (
            <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-4 text-center text-slate-500 text-sm">
              Upload the full backtest file to view the equity curve
            </div>
          )}

          {/* Trade Log */}
          {hasTrades ? (
            <div>
              <h3 className="text-sm font-semibold text-white mb-2">
                Trade Log <span className="text-slate-500 font-normal">({run.trades!.length} trades)</span>
              </h3>
              <div className="overflow-x-auto rounded-xl border border-slate-700">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-slate-800/60 border-b border-slate-700">
                      <th className="px-2 py-2 text-left text-slate-400 font-medium">#</th>
                      <th className="px-2 py-2 text-left text-slate-400 font-medium">Time</th>
                      <th className="px-2 py-2 text-left text-slate-400 font-medium">Dir</th>
                      <th className="px-2 py-2 text-left text-slate-400 font-medium">Entry</th>
                      <th className="px-2 py-2 text-left text-slate-400 font-medium">Exit</th>
                      <th className="px-2 py-2 text-left text-slate-400 font-medium">Outcome</th>
                      <th className="px-2 py-2 text-right text-slate-400 font-medium">PnL</th>
                      <th className="px-2 py-2 text-right text-slate-400 font-medium">R:R</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.trades!.map(t => {
                      const outcomeColor = t.outcome === 'HIT_TP1' || t.outcome === 'HIT_TP2'
                        ? 'text-emerald-400' : t.outcome === 'HIT_SL' ? 'text-red-400' : 'text-slate-400';
                      return (
                        <tr key={t.trade_number} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                          <td className="px-2 py-1.5 text-slate-500">{t.trade_number}</td>
                          <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap">{t.entry_time}</td>
                          <td className={`px-2 py-1.5 font-medium ${t.direction === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}>
                            {t.direction}
                          </td>
                          <td className="px-2 py-1.5 text-slate-300 font-mono">${t.entry_price.toFixed(2)}</td>
                          <td className="px-2 py-1.5 text-slate-300 font-mono">${t.exit_price?.toFixed(2) ?? '—'}</td>
                          <td className={`px-2 py-1.5 font-medium ${outcomeColor}`}>
                            {t.outcome?.replace('HIT_', '') ?? '—'}
                          </td>
                          <td className={`px-2 py-1.5 text-right font-semibold ${(t.pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {formatPnl(t.pnl ?? 0)}
                          </td>
                          <td className="px-2 py-1.5 text-right text-slate-300">
                            {t.rr_ratio?.toFixed(2) ?? '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : !hasEquity ? null : (
            <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-4 text-center text-slate-500 text-sm">
              Upload the full backtest file to view individual trades
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// --- Internal metric card ---

interface MetricCardProps {
  label: string;
  value: string;
  sub?: string;
  color: 'green' | 'red' | 'amber' | 'blue' | 'slate';
}

const colorMap = {
  green: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', text: 'text-emerald-400', sub: 'text-emerald-500/70' },
  red: { bg: 'bg-red-500/10', border: 'border-red-500/20', text: 'text-red-400', sub: 'text-red-500/70' },
  amber: { bg: 'bg-amber-500/10', border: 'border-amber-500/20', text: 'text-amber-400', sub: 'text-amber-500/70' },
  blue: { bg: 'bg-blue-500/10', border: 'border-blue-500/20', text: 'text-blue-400', sub: 'text-blue-500/70' },
  slate: { bg: 'bg-slate-500/10', border: 'border-slate-500/20', text: 'text-slate-300', sub: 'text-slate-500' },
};

function MetricCard({ label, value, sub, color }: MetricCardProps) {
  const c = colorMap[color];
  return (
    <div className={`${c.bg} border ${c.border} rounded-xl p-3`}>
      <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-base font-bold ${c.text}`}>{value}</div>
      {sub && <div className={`text-[10px] mt-0.5 ${c.sub}`}>{sub}</div>}
    </div>
  );
}
