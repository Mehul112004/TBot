import { useMemo, useState } from 'react';
import { GitCommitHorizontal, Calendar, Coins, ShieldAlert, ArrowUpDown, ChevronDown, ChevronUp } from 'lucide-react';
import type { LoadedBacktestFile, BacktestFileRun } from '../../types/backtestFile';
import Heatmap from './Heatmap';

interface Props {
  loaded: LoadedBacktestFile;
  onSelectRun: (run: BacktestFileRun) => void;
}

type SortKey = 'strategy_name' | 'symbol' | 'timeframe' | 'total_pnl' | 'win_rate' | 'sharpe_ratio' | 'profit_factor' | 'total_trades';
type SortDir = 'asc' | 'desc';

function formatPnl(v: number): string {
  const prefix = v >= 0 ? '+' : '';
  return `${prefix}$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function OverviewPanel({ loaded, onSelectRun }: Props) {
  const { file } = loaded;
  const [sortKey, setSortKey] = useState<SortKey>('total_pnl');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  // Filter to completed runs with trades
  const activeRuns = useMemo(() =>
    file.runs.filter(r => r.status === 'COMPLETED' && r.metrics.total_trades > 0),
    [file.runs]
  );

  // Aggregate stats
  const aggregates = useMemo(() => {
    const totalTrades = activeRuns.reduce((s, r) => s + r.metrics.total_trades, 0);
    const totalPnl = activeRuns.reduce((s, r) => s + r.metrics.total_pnl, 0);
    const profitable = activeRuns.filter(r => r.metrics.total_pnl > 0).length;
    const best = activeRuns.length > 0
      ? activeRuns.reduce((best, r) => r.metrics.total_pnl > best.metrics.total_pnl ? r : best)
      : null;
    const worst = activeRuns.length > 0
      ? activeRuns.reduce((worst, r) => r.metrics.total_pnl < worst.metrics.total_pnl ? r : worst)
      : null;
    return { totalTrades, totalPnl, profitable, unprofitable: activeRuns.length - profitable, best, worst };
  }, [activeRuns]);

  // Sorted leaderboard
  const sortedRuns = useMemo(() => {
    const runs = [...activeRuns];
    runs.sort((a, b) => {
      let av: number | string, bv: number | string;
      switch (sortKey) {
        case 'strategy_name': av = a.strategy_name; bv = b.strategy_name; break;
        case 'symbol': av = a.symbol; bv = b.symbol; break;
        case 'timeframe': av = a.timeframe; bv = b.timeframe; break;
        case 'total_pnl': av = a.metrics.total_pnl; bv = b.metrics.total_pnl; break;
        case 'win_rate': av = a.metrics.win_rate; bv = b.metrics.win_rate; break;
        case 'sharpe_ratio': av = a.metrics.sharpe_ratio; bv = b.metrics.sharpe_ratio; break;
        case 'profit_factor': av = a.metrics.profit_factor; bv = b.metrics.profit_factor; break;
        case 'total_trades': av = a.metrics.total_trades; bv = b.metrics.total_trades; break;
        default: av = 0; bv = 0;
      }
      if (typeof av === 'string' && typeof bv === 'string') {
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return runs;
  }, [activeRuns, sortKey, sortDir]);

  // Heatmap data: Symbol × Strategy → PnL %
  const heatmapData = useMemo(() => {
    const symbols = [...new Set(activeRuns.map(r => r.symbol))].sort();
    const strategies = [...new Set(activeRuns.map(r => r.strategy_name))].sort();
    const cells = activeRuns.map(r => ({
      row: r.symbol,
      col: r.strategy_name,
      value: r.metrics.total_pnl_pct,
      label: `${r.metrics.total_pnl_pct >= 0 ? '+' : ''}${r.metrics.total_pnl_pct.toFixed(1)}%`,
    }));
    return { symbols, strategies, cells };
  }, [activeRuns]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const SortIcon = ({ columnKey }: { columnKey: SortKey }) => {
    if (sortKey !== columnKey) return <ArrowUpDown size={12} className="text-slate-600 ml-1" />;
    return sortDir === 'asc'
      ? <ChevronUp size={12} className="text-emerald-400 ml-1" />
      : <ChevronDown size={12} className="text-emerald-400 ml-1" />;
  };

  return (
    <div className="space-y-6">
      {/* Config Header */}
      <div className="flex flex-wrap gap-4 text-sm">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700">
          <Calendar size={14} className="text-slate-400" />
          <span className="text-slate-300">{file.date}</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700">
          <GitCommitHorizontal size={14} className="text-slate-400" />
          <span className="text-slate-300 font-mono text-xs">{file.last_git_commit_id.substring(0, 8)}</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700">
          <Coins size={14} className="text-slate-400" />
          <span className="text-slate-300">${file.config.initial_capital.toLocaleString()}</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700">
          <ShieldAlert size={14} className="text-slate-400" />
          <span className="text-slate-300">{(file.config.risk_per_trade * 100).toFixed(0)}% risk</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700">
          <span className="text-slate-400 text-xs">Symbols</span>
          <span className="text-slate-300">{file.config.symbols.join(', ')}</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700">
          <span className="text-slate-400 text-xs">Lookback</span>
          <span className="text-slate-300">{file.config.lookback_days}d</span>
        </div>
      </div>

      {/* Aggregate Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <AggCard label="Total Runs" value={activeRuns.length.toString()} icon="📊" color="blue" />
        <AggCard label="Total Trades" value={aggregates.totalTrades.toLocaleString()} icon="📋" color="blue" />
        <AggCard
          label="Net PnL"
          value={formatPnl(aggregates.totalPnl)}
          icon="💰"
          color={aggregates.totalPnl >= 0 ? 'green' : 'red'}
        />
        <AggCard
          label="Profitable Runs"
          value={`${aggregates.profitable} / ${activeRuns.length}`}
          icon="✅"
          color={aggregates.profitable > aggregates.unprofitable ? 'green' : 'red'}
        />
        <AggCard
          label="Best Strategy"
          value={aggregates.best?.strategy_name ?? '—'}
          sub={aggregates.best ? `${aggregates.best.symbol} · ${formatPnl(aggregates.best.metrics.total_pnl)}` : undefined}
          icon="🏆"
          color="green"
        />
        <AggCard
          label="Worst Strategy"
          value={aggregates.worst?.strategy_name ?? '—'}
          sub={aggregates.worst ? `${aggregates.worst.symbol} · ${formatPnl(aggregates.worst.metrics.total_pnl)}` : undefined}
          icon="⚠️"
          color="red"
        />
      </div>

      {/* Heatmap: Symbol × Strategy */}
      <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white mb-3">Symbol × Strategy Performance</h3>
        <Heatmap
          rows={heatmapData.symbols}
          columns={heatmapData.strategies}
          cells={heatmapData.cells}
          valueLabel="PnL %"
          onCellClick={(row, col) => {
            const run = activeRuns.find(r => r.symbol === row && r.strategy_name === col);
            if (run) onSelectRun(run);
          }}
        />
      </div>

      {/* Strategy Leaderboard */}
      <div className="bg-slate-800/30 border border-slate-700 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700">
          <h3 className="text-sm font-semibold text-white">Strategy Leaderboard</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/60">
                {([
                  ['strategy_name', 'Strategy'],
                  ['symbol', 'Symbol'],
                  ['timeframe', 'TF'],
                  ['total_trades', 'Trades'],
                  ['win_rate', 'Win %'],
                  ['total_pnl', 'PnL'],
                  ['sharpe_ratio', 'Sharpe'],
                  ['profit_factor', 'PF'],
                ] as [SortKey, string][]).map(([key, label]) => (
                  <th
                    key={key}
                    className="px-3 py-2.5 text-left text-xs font-medium text-slate-400 cursor-pointer hover:text-slate-200 select-none whitespace-nowrap"
                    onClick={() => handleSort(key)}
                  >
                    <span className="flex items-center">
                      {label}
                      <SortIcon columnKey={key} />
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedRuns.map((run) => (
                <tr
                  key={run.run_id}
                  className="border-b border-slate-700/30 hover:bg-slate-700/20 cursor-pointer transition-colors"
                  onClick={() => onSelectRun(run)}
                >
                  <td className="px-3 py-2.5 text-slate-200 font-medium whitespace-nowrap">{run.strategy_name}</td>
                  <td className="px-3 py-2.5 text-slate-300 font-mono text-xs">{run.symbol}</td>
                  <td className="px-3 py-2.5 text-slate-400 text-xs">{run.timeframe}</td>
                  <td className="px-3 py-2.5 text-slate-300">{run.metrics.total_trades}</td>
                  <td className={`px-3 py-2.5 font-medium ${run.metrics.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {run.metrics.win_rate.toFixed(1)}%
                  </td>
                  <td className={`px-3 py-2.5 font-semibold ${run.metrics.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatPnl(run.metrics.total_pnl)}
                  </td>
                  <td className={`px-3 py-2.5 ${run.metrics.sharpe_ratio >= 1 ? 'text-emerald-400' : run.metrics.sharpe_ratio >= 0 ? 'text-amber-400' : 'text-red-400'}`}>
                    {run.metrics.sharpe_ratio.toFixed(2)}
                  </td>
                  <td className={`px-3 py-2.5 ${run.metrics.profit_factor >= 1.5 ? 'text-emerald-400' : run.metrics.profit_factor >= 1 ? 'text-amber-400' : 'text-red-400'}`}>
                    {run.metrics.profit_factor >= 999 ? '∞' : run.metrics.profit_factor.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// --- Internal helpers ---

interface AggCardProps {
  label: string;
  value: string;
  sub?: string;
  icon: string;
  color: 'green' | 'red' | 'blue' | 'amber';
}

const colorStyles = {
  green: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', text: 'text-emerald-400', sub: 'text-emerald-500/70' },
  red: { bg: 'bg-red-500/10', border: 'border-red-500/20', text: 'text-red-400', sub: 'text-red-500/70' },
  blue: { bg: 'bg-blue-500/10', border: 'border-blue-500/20', text: 'text-blue-400', sub: 'text-blue-500/70' },
  amber: { bg: 'bg-amber-500/10', border: 'border-amber-500/20', text: 'text-amber-400', sub: 'text-amber-500/70' },
};

function AggCard({ label, value, sub, icon, color }: AggCardProps) {
  const c = colorStyles[color];
  return (
    <div className={`${c.bg} border ${c.border} rounded-xl p-3 transition-transform hover:scale-[1.02]`}>
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-sm">{icon}</span>
        <span className="text-[10px] text-slate-400 font-medium uppercase tracking-wider">{label}</span>
      </div>
      <div className={`text-base font-bold ${c.text} truncate`}>{value}</div>
      {sub && <div className={`text-[10px] mt-0.5 ${c.sub} truncate`}>{sub}</div>}
    </div>
  );
}
