export interface ResearchCostScenario {
  name: string;
  bps_per_side: number;
}

export interface ResearchManifestInput {
  name: string;
  hypothesis: string;
  family_id?: string;
  variant_id?: string;
  strategy_name: string;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  train_bars: number;
  test_bars: number;
  step_bars: number;
  holdout_bars: number;
  min_folds: number;
  initial_capital: number;
  risk_pct: number;
  slippage_bps: number;
  bootstrap_repetitions?: number;
  bootstrap_seed?: number;
  cost_scenarios?: ResearchCostScenario[];
}

export interface ResearchExperiment {
  id: string;
  name: string;
  hypothesis: string;
  family_id: string;
  variant_id: string;
  manifest: ResearchManifestInput;
  manifest_sha256: string;
  status: string;
  decision: 'PASS' | 'PROVISIONAL' | 'REJECT' | null;
  evidence_grade: string | null;
  decision_reasons: string[];
  summary: Record<string, unknown> | null;
  error_message: string | null;
  holdout_revealed_at: string | null;
  holdout_revealed_by: string | null;
}

export interface ResearchPreview {
  manifest: ResearchManifestInput;
  manifest_sha256: string;
  evaluation_candle_count: number;
  warmup_bars: number;
  label_span_bars: number;
  folds: Array<{
    fold_number: number;
    train_start: string;
    train_end: string;
    purge_start: string;
    purge_end: string;
    test_start: string;
    test_end: string;
  }>;
  holdout: {
    start: string;
    end: string;
    label_tail_start: string;
    status: string;
  };
}

export interface ResearchDetail {
  experiment: ResearchExperiment;
  folds: Array<Record<string, unknown>>;
  evaluations: Array<Record<string, unknown>>;
  slices: Array<Record<string, unknown>>;
  trial: Record<string, unknown> | null;
}
