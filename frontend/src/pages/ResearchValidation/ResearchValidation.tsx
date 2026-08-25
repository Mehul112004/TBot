import { useEffect, useMemo, useState } from 'react';
import {
  createResearchExperiment,
  executeResearchExperiment,
  fetchStrategies,
  fetchSymbols,
  previewResearchExperiment,
  revealResearchHoldout,
  type StrategyInfo,
} from '../../api/client';
import type { ResearchDetail, ResearchManifestInput, ResearchPreview } from '../../types/research';

const TIMEFRAMES = ['5m', '15m', '30m', '1h', '4h', '1d'];

function asIsoDate(value: string) {
  return new Date(value).toISOString();
}

function metricValue(summary: Record<string, unknown> | null, key: string) {
  const walkForward = summary?.walk_forward as { metrics?: Record<string, unknown> } | undefined;
  const value = walkForward?.metrics?.[key];
  return typeof value === 'number' ? value : null;
}

export default function ResearchValidation() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [preview, setPreview] = useState<ResearchPreview | null>(null);
  const [detail, setDetail] = useState<ResearchDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: 'walk-forward-baseline',
    hypothesis: 'The frozen strategy has positive net out-of-sample expectancy after costs.',
    symbol: '',
    timeframe: '1h',
    strategy_name: '',
    start_date: '',
    end_date: '',
    train_bars: '720',
    test_bars: '120',
    holdout_bars: '240',
    min_folds: '5',
    initial_capital: '10000',
    risk_pct: '0.01',
    slippage_bps: '10',
  });

  useEffect(() => {
    fetchStrategies().then(setStrategies).catch(() => setStrategies([]));
    fetchSymbols('binance').then((items) => {
      setSymbols(items);
      if (items[0]) setForm((previous) => ({ ...previous, symbol: previous.symbol || items[0] }));
    }).catch(() => setSymbols(['BTCUSDT', 'ETHUSDT', 'SOLUSDT']));
  }, []);

  const eligibleStrategies = useMemo(
    () => strategies.filter((strategy) => strategy.supports_historical_backtest && strategy.timeframes.includes(form.timeframe)),
    [strategies, form.timeframe],
  );

  useEffect(() => {
    if (!eligibleStrategies.some((strategy) => strategy.name === form.strategy_name)) {
      setForm((previous) => ({ ...previous, strategy_name: eligibleStrategies[0]?.name || '' }));
    }
  }, [eligibleStrategies, form.strategy_name]);

  const manifest = (): ResearchManifestInput => {
    if (!form.start_date || !form.end_date) throw new Error('Start and end dates are required.');
    if (!form.strategy_name) throw new Error('Select a causal historical strategy.');
    return {
      name: form.name.trim(),
      hypothesis: form.hypothesis.trim(),
      strategy_name: form.strategy_name,
      symbol: form.symbol,
      timeframe: form.timeframe,
      start_date: asIsoDate(form.start_date),
      end_date: asIsoDate(form.end_date),
      train_bars: Number(form.train_bars),
      test_bars: Number(form.test_bars),
      step_bars: Number(form.test_bars),
      holdout_bars: Number(form.holdout_bars),
      min_folds: Number(form.min_folds),
      initial_capital: Number(form.initial_capital),
      risk_pct: Number(form.risk_pct),
      slippage_bps: Number(form.slippage_bps),
    };
  };

  const requestPreview = async () => {
    setLoading(true); setError(null); setPreview(null); setDetail(null);
    try {
      setPreview(await previewResearchExperiment(manifest()));
    } catch (err: unknown) {
      const response = err as { response?: { data?: { error?: string } }; message?: string };
      setError(response.response?.data?.error || response.message || 'Unable to preview this experiment.');
    } finally { setLoading(false); }
  };

  const sealAndRun = async () => {
    setLoading(true); setError(null);
    try {
      const created = await createResearchExperiment(manifest());
      setDetail(await executeResearchExperiment(created.experiment.id));
    } catch (err: unknown) {
      const response = err as { response?: { data?: { error?: string } }; message?: string };
      setError(response.response?.data?.error || response.message || 'Unable to execute the walk-forward experiment.');
    } finally { setLoading(false); }
  };

  const revealHoldout = async () => {
    if (!detail) return;
    setLoading(true); setError(null);
    try { setDetail(await revealResearchHoldout(detail.experiment.id)); }
    catch (err: unknown) {
      const response = err as { response?: { data?: { error?: string } }; message?: string };
      setError(response.response?.data?.error || response.message || 'Unable to reveal the final holdout.');
    } finally { setLoading(false); }
  };

  const update = (key: keyof typeof form, value: string) => setForm((previous) => ({ ...previous, [key]: value }));
  const experiment = detail?.experiment;

  return (
    <div className="h-full overflow-auto" id="research-validation-page">
      <div className="px-6 py-4 border-b border-slate-700">
        <h1 className="text-2xl font-bold text-white">Walk-forward Validation</h1>
        <p className="text-sm text-slate-400 mt-1">Measure frozen strategies on later unseen data before they influence signal ranking.</p>
      </div>
      <div className="grid gap-6 p-6 xl:grid-cols-[360px_1fr]">
        <section className="space-y-4 rounded-xl border border-slate-700 bg-slate-800/40 p-5">
          <h2 className="font-semibold text-slate-200">Sealed experiment</h2>
          <input value={form.name} onChange={(event) => update('name', event.target.value)} placeholder="Experiment name" className="field" />
          <textarea value={form.hypothesis} onChange={(event) => update('hypothesis', event.target.value)} rows={3} className="field" />
          <select value={form.symbol} onChange={(event) => update('symbol', event.target.value)} className="field">
            {symbols.map((symbol) => <option key={symbol}>{symbol}</option>)}
          </select>
          <select value={form.timeframe} onChange={(event) => update('timeframe', event.target.value)} className="field">
            {TIMEFRAMES.map((timeframe) => <option key={timeframe}>{timeframe}</option>)}
          </select>
          <select value={form.strategy_name} onChange={(event) => update('strategy_name', event.target.value)} className="field">
            {eligibleStrategies.map((strategy) => <option key={strategy.name}>{strategy.name}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-3">
            <input type="date" value={form.start_date} onChange={(event) => update('start_date', event.target.value)} className="field" />
            <input type="date" value={form.end_date} onChange={(event) => update('end_date', event.target.value)} className="field" />
          </div>
          <div className="grid grid-cols-3 gap-3 text-xs text-slate-400">
            <label>Train bars<input type="number" value={form.train_bars} onChange={(event) => update('train_bars', event.target.value)} className="field mt-1" /></label>
            <label>Test bars<input type="number" value={form.test_bars} onChange={(event) => update('test_bars', event.target.value)} className="field mt-1" /></label>
            <label>Holdout bars<input type="number" value={form.holdout_bars} onChange={(event) => update('holdout_bars', event.target.value)} className="field mt-1" /></label>
          </div>
          <label className="block text-xs text-slate-400">Cost, bps per side<input type="number" value={form.slippage_bps} onChange={(event) => update('slippage_bps', event.target.value)} className="field mt-1" /></label>
          <button onClick={requestPreview} disabled={loading} className="w-full rounded-lg bg-slate-700 py-2.5 text-sm font-medium text-white hover:bg-slate-600 disabled:opacity-50">Preview chronology</button>
          <button onClick={sealAndRun} disabled={loading || !preview} className="w-full rounded-lg bg-emerald-600 py-2.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50">{loading ? 'Working…' : 'Seal & run OOS folds'}</button>
          <p className="text-xs leading-5 text-slate-500">The latest holdout stays sealed until all OOS folds and gates are complete.</p>
        </section>

        <section className="space-y-5">
          {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">{error}</div>}
          {preview && !detail && <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-5">
            <h2 className="font-semibold text-white">Chronology preview</h2>
            <p className="mt-1 text-sm text-slate-400">{preview.evaluation_candle_count.toLocaleString()} evaluation candles · {preview.folds.length} non-overlapping OOS folds · {preview.label_span_bars}-bar label horizon</p>
            <div className="mt-4 space-y-2 text-sm text-slate-300">{preview.folds.map((fold) => <div key={fold.fold_number} className="rounded bg-slate-900/60 p-3">Fold {fold.fold_number}: test {new Date(fold.test_start).toLocaleDateString()} → {new Date(fold.test_end).toLocaleDateString()}</div>)}</div>
            <p className="mt-4 text-sm text-amber-300">Sealed holdout: {new Date(preview.holdout.start).toLocaleDateString()} → {new Date(preview.holdout.end).toLocaleDateString()}</p>
          </div>}
          {experiment && <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-white">{experiment.name}</h2><p className="mt-1 text-sm text-slate-400">{experiment.hypothesis}</p></div><span className="rounded-full bg-slate-700 px-3 py-1 text-xs font-semibold text-emerald-300">{experiment.decision || experiment.status}</span></div>
            <div className="mt-5 grid gap-3 sm:grid-cols-4">
              <Metric label="OOS candidates" value={metricValue(experiment.summary, 'evaluated_candidates')?.toString() || '—'} />
              <Metric label="Mean net R" value={metricValue(experiment.summary, 'mean_net_r')?.toFixed(3) || '—'} />
              <Metric label="Win rate" value={metricValue(experiment.summary, 'net_win_rate') !== null ? `${metricValue(experiment.summary, 'net_win_rate')?.toFixed(1)}%` : '—'} />
              <Metric label="Evidence grade" value={experiment.evidence_grade || '—'} />
            </div>
            <div className="mt-5 text-sm text-slate-400">Reasons: {experiment.decision_reasons.join(', ') || 'Awaiting evaluation'}</div>
            {experiment.status === 'WALK_FORWARD_COMPLETE' && !experiment.holdout_revealed_at && <button onClick={revealHoldout} disabled={loading} className="mt-5 rounded-lg border border-amber-400/40 bg-amber-400/10 px-4 py-2 text-sm font-medium text-amber-200 hover:bg-amber-400/20 disabled:opacity-50">Reveal final holdout</button>}
            {experiment.holdout_revealed_at && <p className="mt-5 text-sm text-amber-300">Final holdout was revealed on {new Date(experiment.holdout_revealed_at).toLocaleString()}.</p>}
          </div>}
          {!preview && !detail && !error && <div className="rounded-xl border border-dashed border-slate-700 p-10 text-center text-slate-500">Preview a frozen strategy configuration to inspect its folds before any outcomes are calculated.</div>}
        </section>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-slate-900/60 p-3"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 text-lg font-semibold text-slate-100">{value}</div></div>;
}
