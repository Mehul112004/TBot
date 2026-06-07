// Types for backtest JSON files produced by run_comprehensive_backtest.py

import type { BacktestMetrics, EquityCurvePoint, BacktestTrade } from './backtest';

export interface BacktestFileConfig {
  symbols: string[];
  timeframes: string[];
  lookback_days: number;
  initial_capital: number;
  risk_per_trade: number;
}

export interface BacktestFileRun {
  symbol: string;
  timeframe: string;
  strategy_name: string;
  run_id: string;
  status: string;
  metrics: BacktestMetrics;
  trades?: BacktestTrade[];       // only present in full files
  equity_curve?: EquityCurvePoint[]; // only present in full files
}

export interface BacktestFile {
  last_git_commit_id: string;
  date: string;
  config: BacktestFileConfig;
  runs: BacktestFileRun[];
}

export interface LoadedBacktestFile {
  file: BacktestFile;
  fileName: string;
  fileId: string;
  loadedAt: Date;
  isFull: boolean; // true if trades/equity_curve data exists
}
