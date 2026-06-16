import os
from datetime import datetime
import atexit
from flask import Flask
from flask_cors import CORS
from sqlalchemy import text
from app.models.db import db
from app.blueprints.data import data_bp
from app.blueprints.indicators_bp import indicators_bp
from app.blueprints.sr_zones_bp import sr_zones_bp
from app.blueprints.strategies_bp import strategies_bp
from app.blueprints.signals_bp import signals_bp
from app.blueprints.backtest_bp import backtest_bp
from app.blueprints.alerts_bp import alerts_bp
from app.blueprints.market_bp import market_bp

def create_app(test_config=None):
    app = Flask(__name__)
    CORS(app)
    
    # Configure Database
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/signals_db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Apply test overrides
    if test_config:
        app.config.update(test_config)

    db.init_app(app)

    # Register blueprints
    app.register_blueprint(data_bp, url_prefix='/api/data')
    app.register_blueprint(indicators_bp, url_prefix='/api/indicators')
    app.register_blueprint(sr_zones_bp, url_prefix='/api/sr-zones')
    app.register_blueprint(strategies_bp, url_prefix='/api/strategies')
    app.register_blueprint(signals_bp, url_prefix='/api/signals')
    app.register_blueprint(backtest_bp, url_prefix='/api/backtest')
    app.register_blueprint(alerts_bp, url_prefix='/api/alerts')
    app.register_blueprint(market_bp, url_prefix='/api/market')

    print(f"App started at ===> {datetime.now()}", flush=True)

    with app.app_context():
        # Create tables (includes indian_instruments)
        try:
            db.create_all()
        except Exception as e:
            print(f"[create_app] db.create_all() failed (DB may be unreachable): {e}")
        
        # Backward compatibility column add
        try:
            db.session.execute(text("ALTER TABLE watching_setups ADD COLUMN telegram_message_id VARCHAR(50);"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Phase 3: Confluence engine columns
        for col_ddl in [
            "ALTER TABLE candles ADD COLUMN is_closed BOOLEAN DEFAULT TRUE",
            "ALTER TABLE watching_setups ADD COLUMN context_data JSONB",
            "ALTER TABLE confirmed_signals ADD COLUMN context_data JSONB",
            "ALTER TABLE confirmed_signals ADD COLUMN telegram_status VARCHAR(20) DEFAULT 'PENDING'",
            "ALTER TABLE confirmed_signals ADD COLUMN telegram_retries INTEGER DEFAULT 0",
            "ALTER TABLE confirmed_signals ADD COLUMN telegram_message_id VARCHAR(50)",
        ]:
            try:
                db.session.execute(text(col_ddl))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Phase 3 (Indian Market): market_type column on all tables
        market_type_migrations = [
            "ALTER TABLE candles ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            "ALTER TABLE sr_zones ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            "ALTER TABLE watching_setups ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            "ALTER TABLE confirmed_signals ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            "ALTER TABLE rejected_signals ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            "ALTER TABLE analysis_sessions ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            "ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            "ALTER TABLE price_alerts ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) DEFAULT 'CRYPTO'",
            # Update sr_zones unique constraint to include market_type
            "ALTER TABLE sr_zones DROP CONSTRAINT IF EXISTS uq_sr_zone",
            "ALTER TABLE sr_zones ADD CONSTRAINT uq_sr_zone UNIQUE (symbol, timeframe, price_level, detection_method, market_type)",
            # Indexes for market_type filter queries
            "CREATE INDEX IF NOT EXISTS idx_watching_setups_market_type ON watching_setups(market_type)",
            "CREATE INDEX IF NOT EXISTS idx_confirmed_signals_market_type ON confirmed_signals(market_type)",
            "CREATE INDEX IF NOT EXISTS idx_rejected_signals_market_type ON rejected_signals(market_type)",
            "CREATE INDEX IF NOT EXISTS idx_analysis_sessions_market_type ON analysis_sessions(market_type)",
            "CREATE INDEX IF NOT EXISTS idx_backtest_runs_market_type ON backtest_runs(market_type)",
            "CREATE INDEX IF NOT EXISTS idx_backtest_trades_market_type ON backtest_trades(market_type)",
            "CREATE INDEX IF NOT EXISTS idx_price_alerts_market_type ON price_alerts(market_type)",
            "CREATE INDEX IF NOT EXISTS idx_candles_market_type ON candles(market_type)",
            "CREATE INDEX IF NOT EXISTS idx_sr_zones_market_type ON sr_zones(market_type)",
            "CREATE INDEX IF NOT EXISTS idx_llm_prompt_logs_market_type ON llm_prompt_logs(market_type)",
        ]
        for ddl in market_type_migrations:
            try:
                db.session.execute(text(ddl))
                db.session.commit()
            except Exception as e:
                db.session.rollback()

        # Initialize strategy registry
        try:
            from app.core.strategy_loader import registry
            registry.load_builtin_strategies()
            registry.sync_with_db()
        except Exception as e:
            print(f"[create_app] Strategy registry init failed: {e}")

        # Initialize market provider registry
        try:
            from app.providers import register_provider
            from app.providers.binance_provider import BinanceProvider
            register_provider('CRYPTO', BinanceProvider())
            print("[create_app] BinanceProvider registered for CRYPTO market")
        except Exception as e:
            print(f"[create_app] Provider registry init failed: {e}")

    # Initialize background scheduler and live scanner (only in non-testing mode)
    if not app.config.get('TESTING', False):
        try:
            from app.core.scanner import live_scanner
            live_scanner.set_app(app)
            atexit.register(live_scanner.stop_all)

            from app.core.scheduler import init_scheduler
            init_scheduler(app, live_scanner)
            
            from app.core.llm_queue import llm_queue
            llm_queue.set_app(app)
            llm_queue.start()
            atexit.register(llm_queue.stop)
            
            from app.core.telegram_queue import telegram_queue
            telegram_queue.set_app(app)
            telegram_queue.start()
            atexit.register(telegram_queue.stop)
            
            from app.core.outcome_tracker import outcome_tracker
            outcome_tracker.set_app(app)
            outcome_tracker.rebuild_cache()

            from app.core.price_alert_tracker import price_alert_tracker
            price_alert_tracker.set_app(app)
            price_alert_tracker.rebuild_cache()
        except Exception as e:
            print(f"[create_app] Background services init failed (DB may be unreachable): {e}")

        # Initialize Angel One provider (non-blocking, only if env vars are set)
        try:
            if os.environ.get('ANGELONE_API_KEY'):
                from app.providers.angelone_provider import AngelOneProvider
                from app.providers import register_provider
                with app.app_context():
                    angelone = AngelOneProvider()
                register_provider('INDIAN', angelone)
                print("[create_app] AngelOneProvider registered for INDIAN market")
        except Exception as e:
            print(f"[create_app] AngelOne provider init failed: {e}")

    return app
