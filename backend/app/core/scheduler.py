"""
Background Refresh Scheduler
Uses APScheduler to periodically recalculate S/R zones.
- Full 4h refresh: every 4h candle close (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
- Full 1D refresh: daily at 00:02 UTC (only once per day)
- Minor update: every 1h candle close

All jobs filter to active sessions only (FIX-SCH-1), use staggered minute
offsets to avoid concurrent DB commits (FIX-SCH-5), and include
coalesce + max_instances guards (FIX-SCH-10).
"""

import atexit
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.core.sr_engine import SREngine
from app.core.indicator_service import IndicatorService
from app.core.config import SUPPORTED_SYMBOLS, SUPPORTED_INDIAN_SYMBOLS


# Timeframes for each job type
FULL_REFRESH_4H_TIMEFRAMES = ['4h']
FULL_REFRESH_1D_TIMEFRAMES = ['1d']
MINOR_UPDATE_TIMEFRAMES = ['1h', '30m', '15m']
ALL_TIMEFRAMES = list(set(FULL_REFRESH_4H_TIMEFRAMES + FULL_REFRESH_1D_TIMEFRAMES + MINOR_UPDATE_TIMEFRAMES))

scheduler = BackgroundScheduler(daemon=True)


def _get_active_symbols(scanner):
    """Return active sessions with (symbol, market_type) pairs."""
    try:
        active_sessions = scanner.get_active_sessions()
        return list({(s['symbol'], s.get('market_type', 'CRYPTO')) for s in active_sessions})
    except Exception:
        return []


def full_zone_refresh_4h(app, scanner):
    """
    Runs every 4 hours (aligned to 4h candle closes).
    For each active symbol × [4h]: full detection → merge → score → persist.
    Invalidates indicator cache for affected symbol/timeframe pairs.
    """
    with app.app_context():
        active = _get_active_symbols(scanner)
        if not active:
            print("[Scheduler] No active sessions — skipping 4h full refresh.")
            return
        print(f"[Scheduler] Starting 4h S/R zone refresh for {active}...")
        for symbol, market_type in active:
            for timeframe in FULL_REFRESH_4H_TIMEFRAMES:
                try:
                    SREngine.full_refresh(symbol, timeframe, market_type=market_type)
                    IndicatorService.invalidate_cache(symbol, timeframe)
                except Exception as e:
                    print(f"[Scheduler] Error refreshing {symbol}/{timeframe} [{market_type}]: {e}")
        print("[Scheduler] 4h full zone refresh complete.")


def full_zone_refresh_1d(app, scanner):
    """
    Runs once per day at 00:02 UTC (after daily candle close).
    For each active symbol × [1D]: full detection → merge → score → persist.
    """
    with app.app_context():
        active = _get_active_symbols(scanner)
        if not active:
            print("[Scheduler] No active sessions — skipping 1D full refresh.")
            return
        print(f"[Scheduler] Starting 1D S/R zone refresh for {active}...")
        for symbol, market_type in active:
            for timeframe in FULL_REFRESH_1D_TIMEFRAMES:
                try:
                    SREngine.full_refresh(symbol, timeframe, market_type=market_type)
                    IndicatorService.invalidate_cache(symbol, timeframe)
                except Exception as e:
                    print(f"[Scheduler] Error refreshing {symbol}/{timeframe} [{market_type}]: {e}")
        print("[Scheduler] 1D full zone refresh complete.")


def minor_zone_update(app, scanner):
    """
    Runs every 1 hour at :03.
    For each active symbol × [1h, 15m]: swing point detection on latest window.
    Adds new swing points to DB without full recalculation.
    """
    with app.app_context():
        active = _get_active_symbols(scanner)
        if not active:
            print("[Scheduler] No active sessions — skipping minor update.")
            return
        print(f"[Scheduler] Starting minor S/R zone update for {active}...")
        for symbol, market_type in active:
            for timeframe in MINOR_UPDATE_TIMEFRAMES:
                try:
                    SREngine.minor_update(symbol, timeframe, market_type=market_type)
                except Exception as e:
                    print(f"[Scheduler] Error updating {symbol}/{timeframe} [{market_type}]: {e}")
        print("[Scheduler] Minor zone update complete.")


def startup_full_refresh(app, scanner):
    """
    One-shot refresh fired on application boot (FIX-SCH-7).
    Ensures zones are fresh even if the server restarted mid-cycle.
    Refreshes crypto + Indian symbols.
    """
    with app.app_context():
        active = _get_active_symbols(scanner)
        if not active:
            active = [(s, 'CRYPTO') for s in SUPPORTED_SYMBOLS]
        print(f"[Scheduler] Startup full refresh for {active}...", flush=True)
        for symbol, market_type in active:
            for timeframe in ALL_TIMEFRAMES:
                try:
                    SREngine.full_refresh(symbol, timeframe, market_type=market_type)
                    IndicatorService.invalidate_cache(symbol, timeframe)
                except Exception as e:
                    print(f"[Scheduler] Startup refresh error {symbol}/{timeframe} [{market_type}]: {e}", flush=True)
        print("[Scheduler] Startup full refresh complete.", flush=True)


def init_scheduler(app, scanner):
    """
    Initialize and start the background scheduler within the Flask app context.
    Jobs are scheduled to run 1 minute after candle close times to ensure
    the closing candle has been stored in the database.

    Args:
        app: Flask application instance
        scanner: LiveScanner instance (for active session filtering)
    """
    # --- Cold-start: delayed one-shot refresh (FIX-SCH-7) ---
    # Delay by 5 minutes to allow historical candle backfill to complete
    run_time = datetime.now() + timedelta(minutes=3)
    print(f"[Scheduler] Scheduling startup full refresh to run at {run_time} (5 minutes delay).", flush=True)
    
    scheduler.add_job(
        func=startup_full_refresh,
        args=[app, scanner],
        trigger='date',  # fire once 5 minutes after startup
        run_date=run_time,
        id='startup_full_refresh',
        replace_existing=True,
    )

    # --- 4h zones: every 4h at :01 (FIX-SCH-2/5) ---
    scheduler.add_job(
        func=full_zone_refresh_4h,
        args=[app, scanner],
        trigger='cron',
        hour='0,4,8,12,16,20',
        minute=1,
        id='full_zone_refresh_4h',
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=120,
    )

    # --- 1D zones: only at daily close 00:02 UTC (FIX-SCH-2/5) ---
    scheduler.add_job(
        func=full_zone_refresh_1d,
        args=[app, scanner],
        trigger='cron',
        hour=0,
        minute=2,
        id='full_zone_refresh_1d',
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=180,
    )

    # --- Minor update (1h/15m): every hour at :03 (FIX-SCH-2/5) ---
    scheduler.add_job(
        func=minor_zone_update,
        args=[app, scanner],
        trigger='cron',
        minute=3,
        id='minor_zone_update',
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    scheduler.start()
    print("[Scheduler] Background scheduler started.", flush=True)
    print("[Scheduler] 4h full refresh: every 4h at :01 UTC", flush=True)
    print("[Scheduler] 1D full refresh: daily at 00:02 UTC", flush=True)
    print("[Scheduler] Minor zone update: every 1h at :03 UTC", flush=True)

    # Ensure scheduler shuts down cleanly when the app exits
    atexit.register(lambda: scheduler.shutdown(wait=False))
