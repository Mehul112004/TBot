"""
Backtesting Engine v4.0

Core engine for running strategies against historical data and computing
performance metrics.

Key design choices:
  - Next-bar-open entry (realistic fill, no lookahead)
  - Single open position with cooldown after exit
  - Entry-candle-aware, gap-aware outcome resolution
  - Same-bar conflict: SL wins (conservative)
  - Net P&L/R metrics and time-based daily risk ratios
"""

import json
import hashlib
import uuid
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

from app.core.base_strategy import BaseStrategy, SetupSignal
from app.core.data_utils import TIMEFRAME_MS
from app.core.strategy_runner import StrategyRunner
from app.models.db import db, Candle, BacktestRun, BacktestTrade


class BacktestEngine:
    """
    Orchestrates a full backtest: data loading, strategy execution,
    trade simulation, and metrics calculation.
    """

    VALID_TIMEFRAMES = ['5m', '15m', '30m', '1h', '4h', '1d']  # Primary signal TFs
    ENGINE_VERSION = '4.0.0'

    @staticmethod
    def _utc_naive_timestamp(value) -> pd.Timestamp:
        """Normalize a timestamp to a comparable UTC-naive Timestamp."""
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            raise ValueError("Timestamp cannot be null")
        if ts.tzinfo is not None:
            ts = ts.tz_convert('UTC').tz_localize(None)
        return ts

    @classmethod
    def validate_candle_data(
        cls,
        candle_df: pd.DataFrame,
        timeframe: str | None = None,
        require_volume: bool = True,
        check_gaps: bool = True,
    ) -> pd.DataFrame:
        """Validate and normalize OHLCV input, failing closed on corrupt data."""
        required = ['open_time', 'open', 'high', 'low', 'close']
        if require_volume:
            required.append('volume')
        missing = [col for col in required if col not in candle_df.columns]
        if missing:
            raise ValueError(f"Candle data is missing required columns: {missing}")
        if candle_df.empty:
            raise ValueError("Candle data is empty")

        df = candle_df.copy()
        parsed_times = pd.to_datetime(df['open_time'], errors='coerce', utc=True)
        if parsed_times.isna().any():
            raise ValueError("Candle data contains invalid open_time values")
        df['open_time'] = parsed_times.dt.tz_localize(None)

        if df['open_time'].duplicated().any():
            duplicate = df.loc[df['open_time'].duplicated(), 'open_time'].iloc[0]
            raise ValueError(f"Duplicate candle timestamp detected: {duplicate}")
        if not df['open_time'].is_monotonic_increasing:
            raise ValueError("Candle timestamps must be strictly increasing")

        numeric_cols = ['open', 'high', 'low', 'close']
        if require_volume:
            numeric_cols.append('volume')
        for col in numeric_cols:
            values = pd.to_numeric(df[col], errors='coerce')
            if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
                raise ValueError(f"Candle data contains non-finite {col} values")
            df[col] = values.astype(float)

        if (df[['open', 'high', 'low', 'close']] <= 0).any().any():
            raise ValueError("OHLC prices must be positive")
        if require_volume and (df['volume'] < 0).any():
            raise ValueError("Candle volume cannot be negative")
        if (df['high'] < df[['open', 'close']].max(axis=1)).any():
            raise ValueError("Candle high is below its open or close")
        if (df['low'] > df[['open', 'close']].min(axis=1)).any():
            raise ValueError("Candle low is above its open or close")
        if (df['high'] < df['low']).any():
            raise ValueError("Candle high is below candle low")
        if 'is_closed' in df.columns and not df['is_closed'].fillna(False).astype(bool).all():
            raise ValueError("Candle data contains rows not marked closed")

        if check_gaps and timeframe:
            tf_ms = TIMEFRAME_MS.get(timeframe)
            if tf_ms is None:
                raise ValueError(f"Unknown timeframe: {timeframe}")
            expected = pd.Timedelta(milliseconds=tf_ms)
            deltas = df['open_time'].diff().iloc[1:]
            bad = deltas != expected
            if bad.any():
                first_bad_pos = int(np.flatnonzero(bad.to_numpy())[0]) + 1
                previous = df['open_time'].iloc[first_bad_pos - 1]
                current = df['open_time'].iloc[first_bad_pos]
                raise ValueError(
                    f"Candle gap detected between {previous} and {current}; "
                    f"expected {timeframe} spacing"
                )

        return df.reset_index(drop=True)

    # ═══════════════════════════════════════════════════════════════
    #  Trade Simulation
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def simulate_trades(
        signals: list[SetupSignal],
        candle_df: pd.DataFrame,
        initial_capital: float,
        risk_pct: float,
        trail_stop: bool = False,
        slippage_bps: float = 10.0,
        cooldown_bars: int = 5,
        unfavorable_expiry_bars: int = 8,
        favorable_expiry_bars: int = 24,
        audit: dict | None = None,
    ) -> list[dict]:
        """
        Resolve trade outcomes with a causal, single-position portfolio model.

        Signals enter at the next bar's open. The entry candle is included in
        outcome evaluation. Only one position may be active, and cooldown starts
        after its exit, so later sizing never uses P&L that was unknown at entry.

        Same-bar conflict rule: If SL and TP are hit on the same candle,
        SL wins (conservative assumption).

        Args:
            signals: List of SetupSignal objects from strategy execution.
            candle_df: Full OHLCV DataFrame sorted by open_time.
            initial_capital: Starting capital for position sizing.
            risk_pct: Fraction of capital risked per trade (e.g. 0.01 = 1%).
            slippage_bps: All-in execution cost in basis points per side.
            cooldown_bars: Closed bars required after an exit before re-entry.
            unfavorable_expiry_bars: Maximum bars while price is unfavorable.
            favorable_expiry_bars: Maximum bars while price is favorable.

        Returns:
            List of trade dicts with all fields needed for BacktestTrade.
        """
        if audit is not None:
            audit.clear()
            audit.update({
                'input_signals': len(signals),
                'accepted_trades': 0,
                'rejections': {},
            })

        def reject(reason: str):
            if audit is not None:
                rejections = audit['rejections']
                rejections[reason] = rejections.get(reason, 0) + 1

        if not signals:
            return []
        if trail_stop:
            raise ValueError(
                "Trailing-stop backtests are disabled: OHLC bars cannot resolve "
                "the intrabar order required to update and hit a trailing stop"
            )
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not 0 < risk_pct <= 1:
            raise ValueError("risk_pct must be greater than 0 and at most 1")
        if slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")
        if cooldown_bars < 0:
            raise ValueError("cooldown_bars cannot be negative")
        if unfavorable_expiry_bars <= 0 or favorable_expiry_bars <= 0:
            raise ValueError("Expiry bars must be positive")

        candle_df = BacktestEngine.validate_candle_data(
            candle_df,
            require_volume=False,
            check_gaps=False,
        )
        trades = []
        equity = round(float(initial_capital), 2)
        slip_frac = slippage_bps / 10000.0
        opens = candle_df['open'].to_numpy(dtype=float)
        highs = candle_df['high'].values
        lows = candle_df['low'].values
        closes = candle_df['close'].values
        times = candle_df['open_time'].tolist()

        time_index = {pd.Timestamp(t).value: i for i, t in enumerate(times)}

        # Highest-confidence candidate wins when multiple strategies fire on the
        # same bar. This removes dependence on caller-provided strategy order.
        resolved_signals = []
        for order, signal in enumerate(signals):
            if signal.timestamp is None:
                raise ValueError(f"Signal from {signal.strategy_name} has no timestamp")
            signal_time = BacktestEngine._utc_naive_timestamp(signal.timestamp)
            confidence = float(signal.confidence or 0.0)
            resolved_signals.append((signal_time, -confidence, signal.strategy_name, order, signal))
        resolved_signals.sort(key=lambda item: item[:4])

        next_allowed_entry_idx = 0

        for sig_time, _, _, _, signal in resolved_signals:
            if signal.entry is None or signal.sl is None or signal.tp1 is None or signal.tp2 is None:
                reject('missing_levels')
                continue

            entry_idx = time_index.get(sig_time.value)
            if entry_idx is None:
                raise ValueError(
                    f"Signal timestamp {sig_time.isoformat()} from "
                    f"{signal.strategy_name} does not match a candle exactly"
                )

            if entry_idx >= len(candle_df) - 1:
                reject('no_next_bar')
                continue

            next_idx = entry_idx + 1
            if next_idx < next_allowed_entry_idx:
                reject('position_open_or_post_exit_cooldown')
                continue

            direction = signal.direction
            if direction not in ('LONG', 'SHORT'):
                raise ValueError(f"Invalid signal direction: {direction}")

            levels = np.array(
                [signal.entry, signal.sl, signal.tp1, signal.tp2],
                dtype=float,
            )
            if not np.isfinite(levels).all() or (levels <= 0).any():
                raise ValueError(f"Signal from {signal.strategy_name} has invalid price levels")
            original_entry, sl, tp1, tp2 = levels.tolist()
            if direction == 'LONG' and not (sl < original_entry < tp1 <= tp2):
                raise ValueError(f"Invalid LONG level ordering from {signal.strategy_name}")
            if direction == 'SHORT' and not (sl > original_entry > tp1 >= tp2):
                raise ValueError(f"Invalid SHORT level ordering from {signal.strategy_name}")

            entry_price = float(opens[next_idx])

            # Structural levels are facts from detection time. A next-open gap
            # must change the available R:R; moving every level by the gap would
            # invent support/targets that the strategy never observed. If entry
            # has already crossed invalidation or TP1, the opportunity was missed.
            if direction == 'LONG' and not (sl < entry_price < tp1):
                reject('next_open_missed_or_invalidated_setup')
                continue
            if direction == 'SHORT' and not (sl > entry_price > tp1):
                reject('next_open_missed_or_invalidated_setup')
                continue

            risk_distance = abs(entry_price - sl)
            if risk_distance <= 0:
                reject('zero_risk_distance')
                continue
            tp1_rr = abs(tp1 - entry_price) / risk_distance
            if tp1_rr < 1.0:
                reject('tp1_below_one_r_at_fill')
                continue

            outcome = 'EXPIRED'
            exit_price = float(closes[-1])
            exit_abs_idx = len(candle_df) - 1
            exit_at_close = True

            # Bar-by-bar processing makes the entry candle, gap handling,
            # intrabar conflict rule, and expiry policy explicit.
            for abs_idx in range(next_idx, len(candle_df)):
                bar_open = float(opens[abs_idx])
                bar_high = float(highs[abs_idx])
                bar_low = float(lows[abs_idx])
                bar_close = float(closes[abs_idx])

                if direction == 'LONG':
                    if bar_open <= sl:
                        outcome, exit_price = 'HIT_SL', bar_open
                    elif bar_open >= tp1:
                        outcome = 'HIT_TP2' if bar_open >= tp2 else 'HIT_TP1'
                        exit_price = bar_open
                    elif bar_low <= sl and bar_high >= tp1:
                        outcome, exit_price = 'HIT_SL', sl
                    elif bar_low <= sl:
                        outcome, exit_price = 'HIT_SL', sl
                    elif bar_high >= tp1:
                        outcome, exit_price = 'HIT_TP1', tp1
                    else:
                        outcome = None
                else:
                    if bar_open >= sl:
                        outcome, exit_price = 'HIT_SL', bar_open
                    elif bar_open <= tp1:
                        outcome = 'HIT_TP2' if bar_open <= tp2 else 'HIT_TP1'
                        exit_price = bar_open
                    elif bar_high >= sl and bar_low <= tp1:
                        outcome, exit_price = 'HIT_SL', sl
                    elif bar_high >= sl:
                        outcome, exit_price = 'HIT_SL', sl
                    elif bar_low <= tp1:
                        outcome, exit_price = 'HIT_TP1', tp1
                    else:
                        outcome = None

                if outcome is not None:
                    exit_abs_idx = abs_idx
                    exit_at_close = False
                    break

                bars_held = abs_idx - next_idx + 1
                favorable = (
                    bar_close >= entry_price if direction == 'LONG'
                    else bar_close <= entry_price
                )
                expiry_limit = favorable_expiry_bars if favorable else unfavorable_expiry_bars
                if bars_held >= expiry_limit or abs_idx == len(candle_df) - 1:
                    outcome = 'EXPIRED'
                    exit_price = bar_close
                    exit_abs_idx = abs_idx
                    exit_at_close = True
                    break

            entry_datetime = pd.Timestamp(times[next_idx]).to_pydatetime()
            exit_timestamp = pd.Timestamp(times[exit_abs_idx])
            if exit_at_close:
                tf_ms = TIMEFRAME_MS.get(signal.timeframe, 0)
                exit_timestamp += pd.Timedelta(milliseconds=tf_ms)
            exit_time = exit_timestamp.to_pydatetime()

            equity_at_entry = equity
            risk_amount = equity * risk_pct
            position_size = risk_amount / risk_distance

            if direction == 'LONG':
                gross_pnl = position_size * (exit_price - entry_price)
            else:
                gross_pnl = position_size * (entry_price - exit_price)

            slippage_cost = position_size * slip_frac * (entry_price + exit_price)
            pnl = round(float(gross_pnl - slippage_cost), 2)
            pnl_pct = (pnl / equity_at_entry) * 100 if equity_at_entry > 0 else 0
            rr_ratio = pnl / risk_amount if risk_amount > 0 else 0
            duration_mins = (exit_time - entry_datetime).total_seconds() / 60.0

            # Use the same cent-rounded P&L for compounding, persistence, and the
            # equity curve so all reported views reconcile exactly.
            equity = round(equity + pnl, 2)
            next_allowed_entry_idx = exit_abs_idx + cooldown_bars + 1

            trades.append({
                'trade_number': len(trades) + 1,
                'entry_time': entry_datetime,
                'exit_time': exit_time,
                'symbol': signal.symbol,
                'timeframe': signal.timeframe,
                'direction': direction,
                'strategy_name': signal.strategy_name,
                'confidence': signal.confidence,
                'entry_price': float(entry_price),
                'sl_price': float(sl),
                'tp1_price': float(tp1),
                'tp2_price': float(tp2),
                'exit_price': float(exit_price),
                'outcome': outcome,
                'pnl': pnl,
                'pnl_pct': round(float(pnl_pct), 4),
                'rr_ratio': round(float(rr_ratio), 4),
                'duration_mins': round(float(duration_mins), 2),
                'equity_at_entry': round(float(equity_at_entry), 2),
                'notes': signal.notes,
            })
            if audit is not None:
                audit['accepted_trades'] = len(trades)

            if equity <= 0:
                break

        return trades

    @staticmethod
    def simulate_candidate_outcomes(
        signals: list[SetupSignal],
        candle_df: pd.DataFrame,
        initial_capital: float,
        risk_pct: float,
        slippage_bps: float = 10.0,
        unfavorable_expiry_bars: int = 8,
        favorable_expiry_bars: int = 24,
    ) -> list[dict]:
        """Evaluate every eligible signal independently.

        This is deliberately different from :meth:`simulate_trades`. The
        single-position simulator answers how the current alert policy behaves;
        this method answers whether each candidate itself was a good opportunity.
        Every signal gets a record, including a transparent skip reason. Each
        accepted candidate delegates its execution to ``simulate_trades`` on a
        bounded signal-to-label window, guaranteeing identical next-open, gap,
        stop-first, target, expiry, and after-cost semantics without allowing
        overlapping candidates to affect one another's sizing or eligibility.
        """
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not 0 < risk_pct <= 1:
            raise ValueError("risk_pct must be greater than 0 and at most 1")
        if slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")

        candle_df = BacktestEngine.validate_candle_data(
            candle_df,
            require_volume=False,
            check_gaps=False,
        )
        time_index = {
            pd.Timestamp(timestamp).value: idx
            for idx, timestamp in enumerate(candle_df['open_time'].tolist())
        }
        max_expiry = max(unfavorable_expiry_bars, favorable_expiry_bars)
        timeframe_delta = pd.Timedelta(milliseconds=TIMEFRAME_MS.get(
            signals[0].timeframe, 0,
        )) if signals else pd.Timedelta(0)
        outcomes = []

        def safe_signal_time(signal: SetupSignal):
            if signal.timestamp is None:
                return None
            return BacktestEngine._utc_naive_timestamp(signal.timestamp).to_pydatetime()

        for candidate_number, signal in enumerate(signals, start=1):
            signal_time = safe_signal_time(signal)
            base = {
                'candidate_number': candidate_number,
                'signal_time': signal_time,
                'symbol': signal.symbol,
                'timeframe': signal.timeframe,
                'strategy_name': signal.strategy_name,
                'direction': signal.direction,
                'confidence': float(signal.confidence or 0.0),
                'regime': getattr(signal, 'regime', 'UNKNOWN'),
                'volatility_regime': getattr(signal, 'volatility_regime', 'UNKNOWN'),
                'structural_bias': getattr(signal, 'structural_bias', 'UNKNOWN'),
                'regime_strength': getattr(signal, 'regime_strength', None),
                'atr': getattr(signal, 'atr', None),
            }

            if signal_time is None:
                outcomes.append({
                    **base,
                    'status': 'SKIPPED',
                    'skip_reason': 'missing_signal_timestamp',
                    'details': {},
                })
                continue

            signal_idx = time_index.get(pd.Timestamp(signal_time).value)
            if signal_idx is None:
                raise ValueError(
                    f"Signal timestamp {signal_time.isoformat()} from "
                    f"{signal.strategy_name} does not match a candle exactly"
                )

            # One signal candle plus every bar that can determine the current
            # hybrid expiry outcome. The slice prevents a candidate evaluator
            # from needlessly receiving future candles beyond its label horizon.
            candidate_window = candle_df.iloc[
                signal_idx:min(len(candle_df), signal_idx + 1 + max_expiry)
            ].copy()
            audit = {}
            try:
                trades = BacktestEngine.simulate_trades(
                    signals=[signal],
                    candle_df=candidate_window,
                    initial_capital=initial_capital,
                    risk_pct=risk_pct,
                    slippage_bps=slippage_bps,
                    unfavorable_expiry_bars=unfavorable_expiry_bars,
                    favorable_expiry_bars=favorable_expiry_bars,
                    audit=audit,
                )
            except ValueError as exc:
                outcomes.append({
                    **base,
                    'status': 'SKIPPED',
                    'skip_reason': 'invalid_signal',
                    'details': {'error': str(exc)},
                })
                continue

            if not trades:
                rejections = audit.get('rejections', {})
                skip_reason = next(iter(rejections), 'not_evaluated')
                outcomes.append({
                    **base,
                    'status': 'SKIPPED',
                    'skip_reason': skip_reason,
                    'details': {'simulation_audit': audit},
                })
                continue

            trade = trades[0]
            risk_distance = abs(trade['entry_price'] - trade['sl_price'])
            offered_tp1_r = (
                abs(trade['tp1_price'] - trade['entry_price']) / risk_distance
                if risk_distance > 0 else None
            )
            offered_tp2_r = (
                abs(trade['tp2_price'] - trade['entry_price']) / risk_distance
                if risk_distance > 0 else None
            )

            # MFE/MAE are conservative OHLC descriptors. Bars before exit use
            # their visible extremes; the exit bar itself is clipped to the
            # executable terminal price so an unknowable post-stop/target move
            # cannot improve a candidate retrospectively.
            exit_timestamp = BacktestEngine._utc_naive_timestamp(trade['exit_time'])
            if trade['outcome'] == 'EXPIRED':
                exit_timestamp -= timeframe_delta
            exit_idx = time_index.get(exit_timestamp.value)
            if exit_idx is None:
                # The terminal bar exists in the bounded candidate window. This
                # branch is defensive so a corrupted timestamp cannot fabricate
                # excursion statistics.
                mfe_r = None
                mae_r = None
            else:
                pre_exit = candle_df.iloc[signal_idx + 1:exit_idx]
                highs = pre_exit['high'].tolist() + [trade['exit_price']]
                lows = pre_exit['low'].tolist() + [trade['exit_price']]
                if signal.direction == 'LONG':
                    mfe_r = (max(highs) - trade['entry_price']) / risk_distance
                    mae_r = (min(lows) - trade['entry_price']) / risk_distance
                else:
                    mfe_r = (trade['entry_price'] - min(lows)) / risk_distance
                    mae_r = (trade['entry_price'] - max(highs)) / risk_distance

            outcomes.append({
                **base,
                'status': 'EVALUATED',
                'skip_reason': None,
                'entry_time': trade['entry_time'],
                'exit_time': trade['exit_time'],
                'entry_price': trade['entry_price'],
                'sl_price': trade['sl_price'],
                'tp1_price': trade['tp1_price'],
                'tp2_price': trade['tp2_price'],
                'exit_price': trade['exit_price'],
                'outcome': trade['outcome'],
                'net_r': trade['rr_ratio'],
                'pnl': trade['pnl'],
                'duration_mins': trade['duration_mins'],
                'offered_tp1_r': round(float(offered_tp1_r), 6) if offered_tp1_r is not None else None,
                'offered_tp2_r': round(float(offered_tp2_r), 6) if offered_tp2_r is not None else None,
                'mfe_r': round(float(mfe_r), 6) if mfe_r is not None else None,
                'mae_r': round(float(mae_r), 6) if mae_r is not None else None,
                'details': {'simulation_audit': audit},
            })

        return outcomes

    # ---------- Equity Curve ----------

    @staticmethod
    def build_equity_curve(
        trades: list[dict],
        initial_capital: float,
        candle_df: pd.DataFrame,
    ) -> list[dict]:
        """
        Build an equity curve as a list of {time, value} dicts.
        Steps through trades chronologically, updating portfolio value.

        Also includes start and end data points for a complete curve.
        """
        if not trades:
            first_time = candle_df['open_time'].iloc[0]
            last_time = candle_df['open_time'].iloc[-1]
            return [
                {'time': first_time.strftime('%Y-%m-%dT%H:%M:%SZ'), 'value': initial_capital},
                {'time': last_time.strftime('%Y-%m-%dT%H:%M:%SZ'), 'value': initial_capital},
            ]

        sorted_trades = sorted(trades, key=lambda t: t['exit_time'])
        curve = []
        equity = initial_capital

        # Starting point
        start_time = candle_df['open_time'].iloc[0]
        curve.append({
            'time': start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'value': round(equity, 2),
        })

        for trade in sorted_trades:
            pnl = trade.get('pnl', 0) or 0
            equity += pnl
            exit_time = trade['exit_time']
            if isinstance(exit_time, datetime):
                time_str = exit_time.strftime('%Y-%m-%dT%H:%M:%SZ')
            else:
                time_str = pd.Timestamp(exit_time).strftime('%Y-%m-%dT%H:%M:%SZ')

            curve.append({
                'time': time_str,
                'value': round(equity, 2),
            })

        # Carry realized equity to the end of the evaluation window. This is
        # required for time-based daily returns instead of per-trade annualizing.
        end_time = pd.Timestamp(candle_df['open_time'].iloc[-1])
        last_curve_time = BacktestEngine._utc_naive_timestamp(curve[-1]['time'])
        if end_time > last_curve_time:
            curve.append({
                'time': end_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'value': round(equity, 2),
            })

        return curve

    # ---------- Metrics Calculator ----------

    @staticmethod
    def compute_metrics(
        trades: list[dict],
        initial_capital: float,
        equity_curve: list[dict],
    ) -> dict:
        """
        Compute summary metrics from net (after-cost) trade results.
        Sharpe/Sortino use calendar-daily realized-equity returns (crypto trades
        365 days/year); they are not annualized from irregular trade frequency.

        Returns dict with: total_trades, win_rate, total_pnl, total_pnl_pct,
        sharpe_ratio, sortino_ratio, max_drawdown, max_drawdown_pct,
        avg_rr, profit_factor, avg_trade_duration_mins, best_trade_pnl,
        worst_trade_pnl.
        """
        if not trades:
            return {
                'total_trades': 0, 'win_rate': 0, 'total_pnl': 0,
                'total_pnl_pct': 0, 'sharpe_ratio': 0, 'sortino_ratio': 0,
                'max_drawdown': 0, 'max_drawdown_pct': 0, 'avg_rr': 0,
                'avg_winner_rr': 0, 'profit_factor': 0,
                'avg_trade_duration_mins': 0,
                'best_trade_pnl': 0, 'worst_trade_pnl': 0,
            }

        pnls = [t.get('pnl', 0) or 0 for t in trades]
        pnl_array = np.array(pnls, dtype=float)

        total_trades = len(trades)
        # A target label is not necessarily a profitable trade after costs.
        # Win rate therefore follows net P&L, which is what the account realizes.
        winners = int(np.sum(pnl_array > 0))
        win_rate = (winners / total_trades) * 100 if total_trades > 0 else 0

        total_pnl = float(np.sum(pnl_array))
        total_pnl_pct = (total_pnl / initial_capital) * 100 if initial_capital > 0 else 0

        daily_returns = np.array([], dtype=float)
        if equity_curve and all('time' in point for point in equity_curve):
            curve_df = pd.DataFrame(equity_curve)
            curve_df['time'] = pd.to_datetime(curve_df['time'], errors='coerce', utc=True)
            curve_df['value'] = pd.to_numeric(curve_df['value'], errors='coerce')
            curve_df = curve_df.dropna().sort_values('time')
            if len(curve_df) >= 2:
                daily_equity = (
                    curve_df.set_index('time')['value']
                    .groupby(level=0).last()
                    .resample('1D').last().ffill()
                )
                daily_returns = daily_equity.pct_change().dropna().to_numpy(dtype=float)

        ann_factor = np.sqrt(365.25)
        if len(daily_returns) > 1 and np.std(daily_returns) > 0:
            sharpe = float(np.mean(daily_returns) / np.std(daily_returns) * ann_factor)
        else:
            sharpe = 0.0

        if len(daily_returns) > 1:
            downside = np.minimum(daily_returns, 0.0)
            downside_deviation = float(np.sqrt(np.mean(np.square(downside))))
            sortino = (
                float(np.mean(daily_returns) / downside_deviation * ann_factor)
                if downside_deviation > 0 else 0.0
            )
        else:
            sortino = 0.0

        # Max Drawdown from equity curve
        if equity_curve and len(equity_curve) > 1:
            values = np.array([p['value'] for p in equity_curve], dtype=float)
            peaks = np.maximum.accumulate(values)
            drawdowns = peaks - values
            max_dd = float(np.max(drawdowns))
            drawdown_pct = np.divide(
                drawdowns,
                peaks,
                out=np.zeros_like(drawdowns),
                where=peaks > 0,
            )
            max_dd_pct = float(np.max(drawdown_pct) * 100)
        else:
            max_dd = 0.0
            max_dd_pct = 0.0

        # Profit Factor
        gross_profit = float(np.sum(pnl_array[pnl_array > 0]))
        gross_loss = float(np.abs(np.sum(pnl_array[pnl_array < 0])))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
            float('inf') if gross_profit > 0 else 0
        )
        # Cap for JSON serialization
        if profit_factor == float('inf'):
            profit_factor = 999.99

        # Average net R for profitable trades.
        winner_rr = [
            t.get('rr_ratio', 0) or 0
            for t in trades
            if (t.get('pnl', 0) or 0) > 0
        ]
        avg_rr = float(np.mean(winner_rr)) if winner_rr else 0
        avg_winner_rr = avg_rr  # alias for clarity

        # Average trade duration
        durations = [t.get('duration_mins', 0) or 0 for t in trades]
        avg_duration = float(np.mean(durations)) if durations else 0

        # Best / worst
        best_pnl = float(np.max(pnl_array)) if len(pnl_array) > 0 else 0
        worst_pnl = float(np.min(pnl_array)) if len(pnl_array) > 0 else 0

        return {
            'total_trades': int(total_trades),
            'win_rate': round(float(win_rate), 2),
            'total_pnl': round(float(total_pnl), 2),
            'total_pnl_pct': round(float(total_pnl_pct), 2),
            'sharpe_ratio': round(float(sharpe), 4),
            'sortino_ratio': round(float(sortino), 4),
            'max_drawdown': round(float(max_dd), 2),
            'max_drawdown_pct': round(float(max_dd_pct), 2),
            'avg_rr': round(float(avg_rr), 4),
            'avg_winner_rr': round(float(avg_winner_rr), 4),
            'profit_factor': round(float(profit_factor), 4),
            'avg_trade_duration_mins': round(float(avg_duration), 2),
            'best_trade_pnl': round(float(best_pnl), 2),
            'worst_trade_pnl': round(float(worst_pnl), 2),
        }

    # ── Main Entry Point ──

    @classmethod
    def run(
        cls,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        strategies: list[BaseStrategy],
        strategy_names: list[str],
        initial_capital: float = 10000.0,
        risk_pct: float = 0.01,
        slippage_bps: float = 10.0,
    ) -> dict:
        """
        Execute a full backtest.

        Steps:
          1. Load closed candles plus a strategy warm-up window from DB
          2. Run all strategies via StrategyRunner.scan_historical()
          3. Keep only signals in the requested evaluation window
          4. Simulate a single-position portfolio with next-open entry
          5. Build equity curve and compute metrics
          6. Persist results plus a reproducibility manifest
        """
        run_id = str(uuid.uuid4())
        warmup_bars = max(
            (strategy.get_required_lookback() for strategy in strategies),
            default=0,
        )
        configuration = {
            'engine_version': cls.ENGINE_VERSION,
            'symbol': symbol,
            'timeframe': timeframe,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'initial_capital': initial_capital,
            'risk_pct': risk_pct,
            'all_in_cost_bps_per_side': slippage_bps,
            'warmup_bars': warmup_bars,
            'cooldown_bars_after_exit': 5,
            'unfavorable_expiry_bars': 8,
            'favorable_expiry_bars': 24,
            'entry_policy': 'next_bar_open_fixed_detection_levels_skip_if_missed',
            'position_policy': 'single_open_position_highest_confidence_first',
            'target_policy': 'tp1_first_unless_open_gaps_beyond_tp2',
            'same_bar_conflict_policy': 'stop_first',
            'strategy_versions': {
                strategy.name: strategy.version for strategy in strategies
            },
        }

        # Create the run record
        run_record = BacktestRun(
            id=run_id,
            symbol=symbol,
            timeframe=timeframe,
            strategy_names=json.dumps(strategy_names),
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            risk_per_trade=risk_pct,
            config_json=json.dumps(configuration, sort_keys=True),
            status='RUNNING',
        )
        db.session.add(run_record)
        db.session.commit()

        evaluation_count = 0
        warmup_count = 0
        try:
            if not strategies:
                raise ValueError("At least one strategy is required")
            incompatible = [
                strategy.name for strategy in strategies
                if timeframe not in strategy.timeframes
            ]
            if incompatible:
                raise ValueError(
                    f"Strategies do not support {timeframe}: {', '.join(incompatible)}"
                )

            tf_ms = TIMEFRAME_MS.get(timeframe)
            if tf_ms is None:
                raise ValueError(f"Unknown timeframe: {timeframe}")
            warmup_start = start_date - timedelta(milliseconds=tf_ms * warmup_bars)

            # 1. Fetch only rows explicitly marked closed. Timestamp finality is
            # checked again below relative to the requested end_date.
            candles = (
                Candle.query
                .filter_by(symbol=symbol, timeframe=timeframe)
                .filter(Candle.is_closed.is_(True))
                .filter(Candle.open_time >= warmup_start)
                .filter(Candle.open_time <= end_date)
                .order_by(Candle.open_time.asc())
                .all()
            )

            if not candles:
                raise ValueError("No closed candle data found for the requested run")

            data = [c.to_dict() for c in candles]
            candle_df = pd.DataFrame(data)
            candle_df['open_time'] = (
                pd.to_datetime(candle_df['open_time'], errors='coerce', utc=True)
                .dt.tz_localize(None)
            )
            start_ts = cls._utc_naive_timestamp(start_date)
            end_ts = cls._utc_naive_timestamp(end_date)
            candle_close_times = candle_df['open_time'] + pd.Timedelta(milliseconds=tf_ms)
            candle_df = candle_df[candle_close_times <= end_ts]
            candle_df = cls.validate_candle_data(
                candle_df,
                timeframe=timeframe,
                require_volume=True,
                check_gaps=True,
            )

            warmup_df = candle_df[candle_df['open_time'] < start_ts]
            evaluation_df = candle_df[candle_df['open_time'] >= start_ts].reset_index(drop=True)
            warmup_count = len(warmup_df)
            evaluation_count = len(evaluation_df)

            if warmup_count < warmup_bars:
                raise ValueError(
                    f"Insufficient warm-up data: {warmup_count} closed candles "
                    f"before start_date (need {warmup_bars})"
                )
            min_evaluation_bars = max(
                strategy.get_min_candles() for strategy in strategies
            )
            if evaluation_count < min_evaluation_bars:
                raise ValueError(
                    f"Insufficient evaluation data: {evaluation_count} closed candles "
                    f"(need at least {min_evaluation_bars})"
                )

            analysis_df = pd.concat(
                [warmup_df.tail(warmup_bars), evaluation_df],
                ignore_index=True,
            )

            fingerprint_cols = ['open_time', 'open', 'high', 'low', 'close', 'volume']
            fingerprint_values = pd.util.hash_pandas_object(
                analysis_df[fingerprint_cols],
                index=False,
            ).values
            configuration['data_fingerprint_sha256'] = hashlib.sha256(
                fingerprint_values.tobytes()
            ).hexdigest()
            configuration['analysis_candle_count'] = len(analysis_df)
            configuration['evaluation_candle_count'] = evaluation_count
            run_record.config_json = json.dumps(configuration, sort_keys=True)

            # 2. Run strategies
            signals = StrategyRunner.scan_historical(
                strategies=strategies,
                symbol=symbol,
                timeframe=timeframe,
                candle_df=analysis_df,
                strict=True,
            )

            # Remove warm-up-period signals. The warm-up rows exist only to
            # initialize causal state and may never enter the reported sample.
            signals = [
                signal for signal in signals
                if signal.timestamp is not None
                and cls._utc_naive_timestamp(signal.timestamp) >= start_ts
            ]

            # 3. Simulate trades
            simulation_audit = {}
            trade_results = cls.simulate_trades(
                signals=signals,
                candle_df=evaluation_df,
                initial_capital=initial_capital,
                risk_pct=risk_pct,
                slippage_bps=slippage_bps,
                audit=simulation_audit,
            )
            configuration['simulation_audit'] = simulation_audit
            run_record.config_json = json.dumps(configuration, sort_keys=True)

            # 4. Build equity curve
            equity_curve = cls.build_equity_curve(
                trades=trade_results,
                initial_capital=initial_capital,
                candle_df=evaluation_df,
            )

            # 5. Compute metrics
            metrics = cls.compute_metrics(
                trades=trade_results,
                initial_capital=initial_capital,
                equity_curve=equity_curve,
            )

            # 6. Persist results
            run_record.status = 'COMPLETED'
            run_record.completed_at = datetime.now(timezone.utc)
            run_record.total_trades = metrics['total_trades']
            run_record.win_rate = metrics['win_rate']
            run_record.total_pnl = metrics['total_pnl']
            run_record.total_pnl_pct = metrics['total_pnl_pct']
            run_record.sharpe_ratio = metrics['sharpe_ratio']
            run_record.sortino_ratio = metrics['sortino_ratio']
            run_record.max_drawdown = metrics['max_drawdown']
            run_record.max_drawdown_pct = metrics['max_drawdown_pct']
            run_record.avg_rr = metrics['avg_rr']
            run_record.profit_factor = metrics['profit_factor']
            run_record.avg_trade_duration_mins = metrics['avg_trade_duration_mins']
            run_record.best_trade_pnl = metrics['best_trade_pnl']
            run_record.worst_trade_pnl = metrics['worst_trade_pnl']
            run_record.equity_curve = json.dumps(equity_curve)

            for t in trade_results:
                trade_record = BacktestTrade(
                    run_id=run_id,
                    trade_number=t['trade_number'],
                    entry_time=t['entry_time'],
                    exit_time=t['exit_time'],
                    symbol=t['symbol'],
                    timeframe=t['timeframe'],
                    direction=t['direction'],
                    strategy_name=t['strategy_name'],
                    confidence=t['confidence'],
                    entry_price=t['entry_price'],
                    sl_price=t['sl_price'],
                    tp1_price=t['tp1_price'],
                    tp2_price=t['tp2_price'],
                    exit_price=t['exit_price'],
                    outcome=t['outcome'],
                    pnl=t['pnl'],
                    pnl_pct=t['pnl_pct'],
                    rr_ratio=t['rr_ratio'],
                    duration_mins=t['duration_mins'],
                    equity_at_entry=t.get('equity_at_entry', 0),
                    notes=t.get('notes', ''),
                )
                db.session.add(trade_record)

            db.session.commit()

            return {
                'run_id': run_id,
                'status': 'COMPLETED',
                'metrics': metrics,
                'equity_curve': equity_curve,
                'trades': trade_results,
                'trade_count': len(trade_results),
                'candle_count': evaluation_count,
                'warmup_candle_count': warmup_count,
                'signal_count': len(signals),
                'simulation_audit': simulation_audit,
                'configuration': configuration,
            }

        except Exception as e:
            run_record.status = 'FAILED'
            run_record.error_message = str(e)
            run_record.completed_at = datetime.now(timezone.utc)
            db.session.commit()

            return {
                'run_id': run_id,
                'status': 'FAILED',
                'error': str(e),
                'metrics': None,
                'equity_curve': [],
                'trades': [],
                'trade_count': 0,
                'candle_count': evaluation_count,
                'warmup_candle_count': warmup_count,
                'signal_count': 0,
                'simulation_audit': None,
                'configuration': configuration,
            }
