from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Candle(db.Model):
    __tablename__ = 'candles'

    # Composite primary key for efficient time-series queries on symbol + timeframe + open_time.
    symbol = db.Column(db.String(50), primary_key=True)
    timeframe = db.Column(db.String(10), primary_key=True)
    open_time = db.Column(db.DateTime(timezone=True), primary_key=True)
    
    open = db.Column(db.Float, nullable=False)
    high = db.Column(db.Float, nullable=False)
    low = db.Column(db.Float, nullable=False)
    close = db.Column(db.Float, nullable=False)
    volume = db.Column(db.Float, nullable=False)
    is_closed = db.Column(db.Boolean, default=True)  # Phase 3: Trap 1 defense

    def to_dict(self):
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'open_time': self.open_time.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'is_closed': self.is_closed,
        }


class SRZone(db.Model):
    __tablename__ = 'sr_zones'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    symbol = db.Column(db.String(50), nullable=False, index=True)
    timeframe = db.Column(db.String(10), nullable=False)           # origin timeframe
    price_level = db.Column(db.Float, nullable=False)              # center of zone
    zone_upper = db.Column(db.Float, nullable=False)               # upper bound
    zone_lower = db.Column(db.Float, nullable=False)               # lower bound
    zone_type = db.Column(db.String(20), nullable=False)           # 'support', 'resistance', 'both'
    detection_method = db.Column(db.String(50), nullable=False)    # 'swing', 'round_number', 'prev_day_hl', 'prev_week_hl'
    strength_score = db.Column(db.Float, default=0.0)              # 0.0–1.0, based on touches + tf weight
    touch_count = db.Column(db.Integer, default=0)                 # how many times price respected this level
    last_tested = db.Column(db.DateTime(timezone=True))            # when price last touched the zone
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())

    # Unique constraint: one zone per symbol+timeframe+price_level+method
    __table_args__ = (
        db.UniqueConstraint('symbol', 'timeframe', 'price_level', 'detection_method', name='uq_sr_zone'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'price_level': self.price_level,
            'zone_upper': self.zone_upper,
            'zone_lower': self.zone_lower,
            'zone_type': self.zone_type,
            'detection_method': self.detection_method,
            'strength_score': self.strength_score,
            'touch_count': self.touch_count,
            'last_tested': self.last_tested.isoformat() if self.last_tested else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Strategy(db.Model):
    __tablename__ = 'strategies'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), unique=True, nullable=False)           # "EMA Crossover"
    description = db.Column(db.Text, default='')
    strategy_type = db.Column(db.String(20), nullable=False)                # 'builtin' or 'custom'
    timeframes = db.Column(db.Text, nullable=False)                         # JSON array: '["1h", "4h"]'
    enabled = db.Column(db.Boolean, default=True)
    min_confidence = db.Column(db.Float, default=0.5)                       # configurable threshold
    code = db.Column(db.Text, nullable=True)                                # Python source (custom only)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'strategy_type': self.strategy_type,
            'timeframes': json.loads(self.timeframes) if self.timeframes else [],
            'enabled': self.enabled,
            'min_confidence': self.min_confidence,
            'has_code': self.code is not None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WatchingSetup(db.Model):
    """
    Tracks detected trade setups that are being monitored (watching cards).
    Created when a strategy fires a SetupSignal, updated on re-fire (dedup),
    expired after N candle closes without re-confirmation.
    """
    __tablename__ = 'watching_setups'

    id = db.Column(db.String(36), primary_key=True)                       # UUID
    session_id = db.Column(db.String(36), nullable=False, index=True)     # Analysis session
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    direction = db.Column(db.String(10), nullable=False)                  # LONG / SHORT
    strategy_name = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    entry = db.Column(db.Float)
    sl = db.Column(db.Float)
    tp1 = db.Column(db.Float)
    tp2 = db.Column(db.Float)
    notes = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='WATCHING')                 # WATCHING / EXPIRED / CONFIRMED / REJECTED
    candles_since_detected = db.Column(db.Integer, default=0)
    expiry_candles = db.Column(db.Integer, default=3)                     # Configurable via env
    detected_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    expired_at = db.Column(db.DateTime(timezone=True), nullable=True)
    zone_description = db.Column(db.Text, default='')                    # e.g. "Resistance at $3,420"
    condition_description = db.Column(db.Text, default='')               # e.g. "Bearish engulfing on 1h close"
    telegram_message_id = db.Column(db.String(50), nullable=True)        # Used to reply with verdicts
    context_data = db.Column(db.JSON, nullable=True)                     # Phase 3: snapshot of zones/indicators/events

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'strategy_name': self.strategy_name,
            'confidence': self.confidence,
            'entry': self.entry,
            'sl': self.sl,
            'tp1': self.tp1,
            'tp2': self.tp2,
            'notes': self.notes,
            'status': self.status,
            'candles_since_detected': self.candles_since_detected,
            'expiry_candles': self.expiry_candles,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'expired_at': self.expired_at.isoformat() if self.expired_at else None,
            'zone_description': self.zone_description,
            'condition_description': self.condition_description,
            'context_data': self.context_data,
        }


class AnalysisSessionRecord(db.Model):
    """
    Lightweight DB record of an analysis session.
    Sessions are ephemeral (in-memory), but persisted here
    for SSE stream reference and watching setup foreign key context.
    """
    __tablename__ = 'analysis_sessions'

    id = db.Column(db.String(36), primary_key=True)                       # UUID
    symbol = db.Column(db.String(50), nullable=False)
    strategy_names = db.Column(db.Text, nullable=False)                   # JSON array
    timeframes = db.Column(db.Text, nullable=False)                       # JSON array
    status = db.Column(db.String(20), default='active')                   # active / stopped
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    stopped_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'symbol': self.symbol,
            'strategy_names': json.loads(self.strategy_names) if self.strategy_names else [],
            'timeframes': json.loads(self.timeframes) if self.timeframes else [],
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'stopped_at': self.stopped_at.isoformat() if self.stopped_at else None,
        }


class ConfirmedSignal(db.Model):
    """
    Final trade signals that have passed the LLM confirmation pipeline.
    Displayed on the Confirmed feed in the UI and sent to Telegram.
    """
    __tablename__ = 'confirmed_signals'

    id = db.Column(db.String(36), primary_key=True)                       # UUID
    watching_setup_id = db.Column(db.String(36), nullable=False)          # Link to origin setup
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    direction = db.Column(db.String(10), nullable=False)                  # LONG / SHORT
    strategy_name = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    
    entry = db.Column(db.Float, nullable=False)
    sl = db.Column(db.Float, nullable=False)
    tp1 = db.Column(db.Float, nullable=False)
    tp2 = db.Column(db.Float, nullable=False)
    
    verdict_status = db.Column(db.String(20), nullable=False)             # CONFIRMED / MODIFIED
    reasoning_text = db.Column(db.Text, nullable=False)
    
    trade_outcome = db.Column(db.String(20), default='ACTIVE')            # ACTIVE / HIT_TP1 / HIT_TP2 / HIT_SL / EXPIRED
    
    telegram_status = db.Column(db.String(20), default='PENDING')         # PENDING / SENT / FAILED
    telegram_retries = db.Column(db.Integer, default=0)
    telegram_message_id = db.Column(db.String(50), nullable=True)         # Useful for reply
    
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    outcome_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    context_data = db.Column(db.JSON, nullable=True)                     # Phase 3: snapshot of zones/indicators/events

    def to_dict(self):
        return {
            'id': self.id,
            'watching_setup_id': self.watching_setup_id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'strategy_name': self.strategy_name,
            'confidence': self.confidence,
            'entry': self.entry,
            'sl': self.sl,
            'tp1': self.tp1,
            'tp2': self.tp2,
            'verdict_status': self.verdict_status,
            'reasoning_text': self.reasoning_text,
            'trade_outcome': self.trade_outcome,
            'telegram_status': self.telegram_status,
            'telegram_retries': self.telegram_retries,
            'telegram_message_id': self.telegram_message_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'outcome_updated_at': self.outcome_updated_at.isoformat() if self.outcome_updated_at else None,
        }


class RejectedSignal(db.Model):
    """
    Trade signals that were rejected by the LLM confirmation pipeline.
    """
    __tablename__ = 'rejected_signals'

    id = db.Column(db.String(36), primary_key=True)                       # UUID
    watching_setup_id = db.Column(db.String(36), nullable=False)          # Link to origin setup
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    direction = db.Column(db.String(10), nullable=False)                  # LONG / SHORT
    strategy_name = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    
    entry = db.Column(db.Float, nullable=True)
    sl = db.Column(db.Float, nullable=True)
    tp1 = db.Column(db.Float, nullable=True)
    tp2 = db.Column(db.Float, nullable=True)
    
    reasoning_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    def to_dict(self):
        return {
            'id': self.id,
            'watching_setup_id': self.watching_setup_id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'strategy_name': self.strategy_name,
            'confidence': self.confidence,
            'entry': self.entry,
            'sl': self.sl,
            'tp1': self.tp1,
            'tp2': self.tp2,
            'reasoning_text': self.reasoning_text,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class BacktestRun(db.Model):
    """
    Stores the configuration and summary metrics for each backtest execution.
    Equity curve is stored as a JSON array of {time, value} dicts.
    """
    __tablename__ = 'backtest_runs'

    id = db.Column(db.String(36), primary_key=True)
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    strategy_names = db.Column(db.Text, nullable=False)          # JSON array
    start_date = db.Column(db.DateTime(timezone=True), nullable=False)
    end_date = db.Column(db.DateTime(timezone=True), nullable=False)
    initial_capital = db.Column(db.Float, nullable=False)
    risk_per_trade = db.Column(db.Float, nullable=False)         # fraction, e.g. 0.01
    config_json = db.Column(db.Text, nullable=True)              # immutable engine/data manifest

    # Summary metrics (populated after run completes)
    total_trades = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float)
    total_pnl = db.Column(db.Float)
    total_pnl_pct = db.Column(db.Float)
    sharpe_ratio = db.Column(db.Float)
    sortino_ratio = db.Column(db.Float)
    max_drawdown = db.Column(db.Float)
    max_drawdown_pct = db.Column(db.Float)
    avg_rr = db.Column(db.Float)
    profit_factor = db.Column(db.Float)
    avg_trade_duration_mins = db.Column(db.Float)
    best_trade_pnl = db.Column(db.Float)
    worst_trade_pnl = db.Column(db.Float)

    status = db.Column(db.String(20), default='RUNNING')         # RUNNING / COMPLETED / FAILED
    error_message = db.Column(db.Text, nullable=True)
    equity_curve = db.Column(db.Text, nullable=True)             # JSON array of {time, value}

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    trades = db.relationship('BacktestTrade', backref='run', lazy='dynamic',
                             cascade='all, delete-orphan')

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'strategy_names': json.loads(self.strategy_names) if self.strategy_names else [],
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'initial_capital': self.initial_capital,
            'risk_per_trade': self.risk_per_trade,
            'configuration': json.loads(self.config_json) if self.config_json else None,
            'total_trades': self.total_trades,
            'win_rate': self.win_rate,
            'total_pnl': self.total_pnl,
            'total_pnl_pct': self.total_pnl_pct,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'avg_rr': self.avg_rr,
            'profit_factor': self.profit_factor,
            'avg_trade_duration_mins': self.avg_trade_duration_mins,
            'best_trade_pnl': self.best_trade_pnl,
            'worst_trade_pnl': self.worst_trade_pnl,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class BacktestTrade(db.Model):
    """
    Individual trade records for a backtest run.
    Each trade has entry/exit prices, SL/TP levels, outcome, PnL, and duration.
    """
    __tablename__ = 'backtest_trades'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(db.String(36), db.ForeignKey('backtest_runs.id'), nullable=False, index=True)

    trade_number = db.Column(db.Integer, nullable=False)
    entry_time = db.Column(db.DateTime(timezone=True), nullable=False)
    exit_time = db.Column(db.DateTime(timezone=True))
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    direction = db.Column(db.String(10), nullable=False)         # LONG / SHORT
    strategy_name = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float)

    entry_price = db.Column(db.Float, nullable=False)
    sl_price = db.Column(db.Float, nullable=False)
    tp1_price = db.Column(db.Float, nullable=False)
    tp2_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float)

    outcome = db.Column(db.String(20))                           # HIT_TP1 / HIT_TP2 / HIT_SL / EXPIRED
    pnl = db.Column(db.Float)
    pnl_pct = db.Column(db.Float)
    rr_ratio = db.Column(db.Float)
    duration_mins = db.Column(db.Float)
    equity_at_entry = db.Column(db.Float)                       # Capital at time of entry (compounding baseline)
    notes = db.Column(db.Text, default='')

    def to_dict(self):
        return {
            'trade_number': self.trade_number,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'strategy_name': self.strategy_name,
            'confidence': self.confidence,
            'entry_price': self.entry_price,
            'sl_price': self.sl_price,
            'tp1_price': self.tp1_price,
            'tp2_price': self.tp2_price,
            'exit_price': self.exit_price,
            'outcome': self.outcome,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'rr_ratio': self.rr_ratio,
            'duration_mins': self.duration_mins,
            'equity_at_entry': self.equity_at_entry,
            'notes': self.notes,
        }

class PriceAlert(db.Model):
    __tablename__ = 'price_alerts'

    id = db.Column(db.String(36), primary_key=True)
    symbol = db.Column(db.String(50), nullable=False, index=True)
    target_price = db.Column(db.Float, nullable=False)
    direction = db.Column(db.String(10), nullable=False)          # ABOVE / BELOW
    alert_type = db.Column(db.String(20), nullable=False)         # ONCE / EVERY_TIME
    status = db.Column(db.String(20), default='ACTIVE')           # ACTIVE / TRIGGERED / CANCELLED
    cross_state = db.Column(db.String(20), nullable=True)         # WAS_ABOVE / WAS_BELOW — tracks crossing side
    note = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    triggered_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cancelled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'target_price': self.target_price,
            'direction': self.direction,
            'alert_type': self.alert_type,
            'status': self.status,
            'cross_state': self.cross_state,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'cancelled_at': self.cancelled_at.isoformat() if self.cancelled_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class LLMPromptLog(db.Model):
    """
    Logs every interaction with the LLM. 
    Loose coupling referencing 'watching_setup_id' since setups can be deleted.
    """
    __tablename__ = 'llm_prompt_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    watching_setup_id = db.Column(db.String(100), index=True) # Loose reference
    symbol = db.Column(db.String(20), nullable=False)
    strategy_name = db.Column(db.String(50), nullable=False)
    model_name = db.Column(db.String(100)) # e.g. google/gemma-4-e4b
    prompt_text = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=True)
    parsed_verdict = db.Column(db.String(20)) # CONFIRM, REJECT, MODIFY, ERROR
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    def to_dict(self):
        return {
            'id': self.id,
            'watching_setup_id': self.watching_setup_id,
            'symbol': self.symbol,
            'strategy_name': self.strategy_name,
            'model_name': self.model_name,
            'prompt_text': self.prompt_text,
            'response_text': self.response_text,
            'parsed_verdict': self.parsed_verdict,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ── Walk-forward research records ──────────────────────────────────────────
#
# These models intentionally sit beside BacktestRun/BacktestTrade rather than
# changing those historical records. A BacktestRun is one atomic simulation;
# a research experiment is a versioned collection of chronological OOS folds,
# cost scenarios, candidate outcomes, and one optional final holdout.


class ResearchExperiment(db.Model):
    __tablename__ = 'research_experiments'

    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    hypothesis = db.Column(db.Text, nullable=False)
    family_id = db.Column(db.String(120), nullable=False, index=True)
    variant_id = db.Column(db.String(120), nullable=False)
    manifest_json = db.Column(db.Text, nullable=False)
    manifest_sha256 = db.Column(db.String(64), nullable=False, unique=True, index=True)

    status = db.Column(db.String(40), nullable=False, default='SEALED')
    decision = db.Column(db.String(20), nullable=True)  # PASS / PROVISIONAL / REJECT
    evidence_grade = db.Column(db.String(20), nullable=True)
    decision_reasons_json = db.Column(db.Text, nullable=True)
    summary_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    engine_version = db.Column(db.String(30), nullable=False)
    strategy_version = db.Column(db.String(50), nullable=False)
    data_fingerprint_sha256 = db.Column(db.String(64), nullable=True)
    holdout_revealed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    holdout_revealed_by = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())

    folds = db.relationship('ResearchFold', backref='experiment', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'name': self.name,
            'hypothesis': self.hypothesis,
            'family_id': self.family_id,
            'variant_id': self.variant_id,
            'manifest': json.loads(self.manifest_json) if self.manifest_json else {},
            'manifest_sha256': self.manifest_sha256,
            'status': self.status,
            'decision': self.decision,
            'evidence_grade': self.evidence_grade,
            'decision_reasons': json.loads(self.decision_reasons_json) if self.decision_reasons_json else [],
            'summary': json.loads(self.summary_json) if self.summary_json else None,
            'error_message': self.error_message,
            'engine_version': self.engine_version,
            'strategy_version': self.strategy_version,
            'data_fingerprint_sha256': self.data_fingerprint_sha256,
            'holdout_revealed_at': self.holdout_revealed_at.isoformat() if self.holdout_revealed_at else None,
            'holdout_revealed_by': self.holdout_revealed_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ResearchFold(db.Model):
    __tablename__ = 'research_folds'

    id = db.Column(db.String(36), primary_key=True)
    experiment_id = db.Column(db.String(36), db.ForeignKey('research_experiments.id'), nullable=False, index=True)
    fold_number = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), nullable=False, default='OOS')  # OOS / HOLDOUT
    train_start = db.Column(db.DateTime(timezone=True), nullable=True)
    train_end = db.Column(db.DateTime(timezone=True), nullable=True)
    purge_start = db.Column(db.DateTime(timezone=True), nullable=True)
    purge_end = db.Column(db.DateTime(timezone=True), nullable=True)
    test_start = db.Column(db.DateTime(timezone=True), nullable=False)
    test_end = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='QUEUED')
    data_fingerprint_sha256 = db.Column(db.String(64), nullable=True)
    configuration_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    evaluations = db.relationship('ResearchEvaluationRun', backref='fold', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('experiment_id', 'kind', 'fold_number', name='uq_research_fold_number'),
    )

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'experiment_id': self.experiment_id,
            'fold_number': self.fold_number,
            'kind': self.kind,
            'train_start': self.train_start.isoformat() if self.train_start else None,
            'train_end': self.train_end.isoformat() if self.train_end else None,
            'purge_start': self.purge_start.isoformat() if self.purge_start else None,
            'purge_end': self.purge_end.isoformat() if self.purge_end else None,
            'test_start': self.test_start.isoformat() if self.test_start else None,
            'test_end': self.test_end.isoformat() if self.test_end else None,
            'status': self.status,
            'data_fingerprint_sha256': self.data_fingerprint_sha256,
            'configuration': json.loads(self.configuration_json) if self.configuration_json else None,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class ResearchEvaluationRun(db.Model):
    __tablename__ = 'research_evaluation_runs'

    id = db.Column(db.String(36), primary_key=True)
    experiment_id = db.Column(db.String(36), db.ForeignKey('research_experiments.id'), nullable=False, index=True)
    fold_id = db.Column(db.String(36), db.ForeignKey('research_folds.id'), nullable=False, index=True)
    track = db.Column(db.String(30), nullable=False)  # candidate_quality / alert_policy
    cost_scenario = db.Column(db.String(80), nullable=False)
    cost_bps_per_side = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), nullable=False, default='QUEUED')
    metrics_json = db.Column(db.Text, nullable=True)
    uncertainty_json = db.Column(db.Text, nullable=True)
    audit_json = db.Column(db.Text, nullable=True)
    result_fingerprint_sha256 = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    outcomes = db.relationship('ResearchCandidateOutcome', backref='evaluation_run', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('fold_id', 'track', 'cost_scenario', name='uq_research_evaluation_scope'),
    )

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'experiment_id': self.experiment_id,
            'fold_id': self.fold_id,
            'track': self.track,
            'cost_scenario': self.cost_scenario,
            'cost_bps_per_side': self.cost_bps_per_side,
            'status': self.status,
            'metrics': json.loads(self.metrics_json) if self.metrics_json else None,
            'uncertainty': json.loads(self.uncertainty_json) if self.uncertainty_json else None,
            'audit': json.loads(self.audit_json) if self.audit_json else None,
            'result_fingerprint_sha256': self.result_fingerprint_sha256,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class ResearchCandidateOutcome(db.Model):
    __tablename__ = 'research_candidate_outcomes'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    experiment_id = db.Column(db.String(36), db.ForeignKey('research_experiments.id'), nullable=False, index=True)
    fold_id = db.Column(db.String(36), db.ForeignKey('research_folds.id'), nullable=False, index=True)
    evaluation_run_id = db.Column(db.String(36), db.ForeignKey('research_evaluation_runs.id'), nullable=False, index=True)
    candidate_number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # EVALUATED / SKIPPED
    skip_reason = db.Column(db.String(100), nullable=True)

    signal_time = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    entry_time = db.Column(db.DateTime(timezone=True), nullable=True)
    exit_time = db.Column(db.DateTime(timezone=True), nullable=True)
    symbol = db.Column(db.String(50), nullable=False, index=True)
    timeframe = db.Column(db.String(10), nullable=False)
    strategy_name = db.Column(db.String(100), nullable=False)
    direction = db.Column(db.String(10), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    regime = db.Column(db.String(30), nullable=True, index=True)
    volatility_regime = db.Column(db.String(30), nullable=True, index=True)
    structural_bias = db.Column(db.String(30), nullable=True)
    regime_strength = db.Column(db.Float, nullable=True)
    atr = db.Column(db.Float, nullable=True)

    entry_price = db.Column(db.Float, nullable=True)
    sl_price = db.Column(db.Float, nullable=True)
    tp1_price = db.Column(db.Float, nullable=True)
    tp2_price = db.Column(db.Float, nullable=True)
    exit_price = db.Column(db.Float, nullable=True)
    outcome = db.Column(db.String(20), nullable=True)
    net_r = db.Column(db.Float, nullable=True)
    pnl = db.Column(db.Float, nullable=True)
    duration_mins = db.Column(db.Float, nullable=True)
    offered_tp1_r = db.Column(db.Float, nullable=True)
    offered_tp2_r = db.Column(db.Float, nullable=True)
    mfe_r = db.Column(db.Float, nullable=True)
    mae_r = db.Column(db.Float, nullable=True)
    details_json = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('evaluation_run_id', 'candidate_number', name='uq_research_candidate_sequence'),
    )

    def to_dict(self):
        import json
        return {
            'candidate_number': self.candidate_number,
            'status': self.status,
            'skip_reason': self.skip_reason,
            'signal_time': self.signal_time.isoformat() if self.signal_time else None,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'strategy_name': self.strategy_name,
            'direction': self.direction,
            'confidence': self.confidence,
            'regime': self.regime,
            'volatility_regime': self.volatility_regime,
            'structural_bias': self.structural_bias,
            'regime_strength': self.regime_strength,
            'atr': self.atr,
            'entry_price': self.entry_price,
            'sl_price': self.sl_price,
            'tp1_price': self.tp1_price,
            'tp2_price': self.tp2_price,
            'exit_price': self.exit_price,
            'outcome': self.outcome,
            'net_r': self.net_r,
            'pnl': self.pnl,
            'duration_mins': self.duration_mins,
            'offered_tp1_r': self.offered_tp1_r,
            'offered_tp2_r': self.offered_tp2_r,
            'mfe_r': self.mfe_r,
            'mae_r': self.mae_r,
            'details': json.loads(self.details_json) if self.details_json else None,
        }


class ResearchMetricSlice(db.Model):
    __tablename__ = 'research_metric_slices'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    experiment_id = db.Column(db.String(36), db.ForeignKey('research_experiments.id'), nullable=False, index=True)
    evaluation_run_id = db.Column(db.String(36), db.ForeignKey('research_evaluation_runs.id'), nullable=True, index=True)
    slice_type = db.Column(db.String(50), nullable=False)
    slice_key = db.Column(db.String(200), nullable=False)
    is_primary = db.Column(db.Boolean, nullable=False, default=True)
    sample_size = db.Column(db.Integer, nullable=False, default=0)
    independent_block_count = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default='COMPLETE')
    metrics_json = db.Column(db.Text, nullable=True)
    uncertainty_json = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('experiment_id', 'evaluation_run_id', 'slice_type', 'slice_key', name='uq_research_metric_slice'),
    )

    def to_dict(self):
        import json
        return {
            'slice_type': self.slice_type,
            'slice_key': self.slice_key,
            'is_primary': self.is_primary,
            'sample_size': self.sample_size,
            'independent_block_count': self.independent_block_count,
            'status': self.status,
            'metrics': json.loads(self.metrics_json) if self.metrics_json else None,
            'uncertainty': json.loads(self.uncertainty_json) if self.uncertainty_json else None,
        }


class ResearchTrial(db.Model):
    __tablename__ = 'research_trials'

    id = db.Column(db.String(36), primary_key=True)
    experiment_id = db.Column(db.String(36), db.ForeignKey('research_experiments.id'), nullable=False, unique=True, index=True)
    family_id = db.Column(db.String(120), nullable=False, index=True)
    variant_id = db.Column(db.String(120), nullable=False)
    hypothesis = db.Column(db.Text, nullable=False)
    trial_kind = db.Column(db.String(30), nullable=False, default='CONFIRMATORY')
    raw_p_value = db.Column(db.Float, nullable=True)
    adjusted_p_value = db.Column(db.Float, nullable=True)
    multiple_testing_method = db.Column(db.String(50), nullable=False, default='benjamini-hochberg')
    family_size = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    def to_dict(self):
        return {
            'experiment_id': self.experiment_id,
            'family_id': self.family_id,
            'variant_id': self.variant_id,
            'hypothesis': self.hypothesis,
            'trial_kind': self.trial_kind,
            'raw_p_value': self.raw_p_value,
            'adjusted_p_value': self.adjusted_p_value,
            'multiple_testing_method': self.multiple_testing_method,
            'family_size': self.family_size,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
