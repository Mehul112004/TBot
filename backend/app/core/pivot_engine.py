"""
Pivot Points Engine
Computes pivot-point support/resistance levels from a previous completed
higher-timeframe candle (default: previous UTC day).

Pivot points are *calculated, forecast* levels (unlike historical swing S/R,
which is *observed*). They produce a small, fixed, clean set of horizontal
levels that reset each period. Two variants are supported:

- Standard / Floor-Trader pivots  : P + R1..R3 + S1..S3  (7 levels)
- Camarilla pivots                : Standard P + H1..H4 + L1..L4 (9 levels)

Camarilla is recommended for crypto intraday: H3/L3 are reversal zones,
H4/L4 are breakout/stop levels, and the Standard P is the daily bias line.

All levels are computed on-the-fly (not persisted) — pivots are cheap (one
query + arithmetic) and reset every period, so persistence adds no value.
"""

from datetime import datetime

from app.models.db import Candle


# ---------------------------------------------------------------------------
# Formula implementations
# ---------------------------------------------------------------------------

def _standard_levels(h: float, l: float, c: float) -> list[tuple[str, float, str]]:
    """
    Standard / Floor-Trader pivots from prior-period H/L/C.
    Returns [(label, level, direction)] where direction is
    'pivot' | 'support' | 'resistance'.
    """
    p = (h + l + c) / 3.0
    rng = h - l
    return [
        ('R3', h + 2.0 * (p - l), 'resistance'),
        ('R2', p + rng, 'resistance'),
        ('R1', 2.0 * p - l, 'resistance'),
        ('P',  p, 'pivot'),
        ('S1', 2.0 * p - h, 'support'),
        ('S2', p - rng, 'support'),
        ('S3', l - 2.0 * (h - p), 'support'),
    ]


def _camarilla_levels(h: float, l: float, c: float) -> list[tuple[str, float, str]]:
    """
    Camarilla pivots (H1..H4, L1..L4) plus the Standard P as the bias line.
    Multipliers are the canonical Nick Stott / platform-standard set.
    """
    rng = h - l
    p = (h + l + c) / 3.0
    return [
        ('H4', c + rng * 1.1 / 2.0,  'resistance'),  # breakout / stop
        ('H3', c + rng * 1.1 / 4.0,  'resistance'),  # reversal zone
        ('H2', c + rng * 1.1 / 6.0,  'resistance'),
        ('H1', c + rng * 1.1 / 12.0, 'resistance'),
        ('P',  p,                     'pivot'),
        ('L1', c - rng * 1.1 / 12.0, 'support'),
        ('L2', c - rng * 1.1 / 6.0,  'support'),
        ('L3', c - rng * 1.1 / 4.0,  'support'),     # reversal zone
        ('L4', c - rng * 1.1 / 2.0,  'support'),     # breakout / stop
    ]


_VARIANTS = {
    'standard':  _standard_levels,
    'camarilla': _camarilla_levels,
}


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------

def _fetch_prev_completed_candle(symbol: str, period: str):
    """
    Fetch the most recent *fully completed* candle for the given period.

    The latest 1D row in the DB may still be forming (today's candle), so we
    take the SECOND most-recent row — that is the previous completed day/week.
    Falls back to the most-recent row if only one exists.
    """
    candles = (
        Candle.query
        .filter_by(symbol=symbol, timeframe=period)
        .order_by(Candle.open_time.desc())
        .limit(2)
        .all()
    )
    if not candles:
        return None
    # candles[0] = current/forming period, candles[1] = previous completed
    return candles[1] if len(candles) >= 2 else candles[0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_pivots(
    symbol: str,
    variant: str = 'camarilla',
    period: str = '1d',
) -> list[dict]:
    """
    Compute pivot-point levels for a symbol.

    Args:
        symbol:  Trading pair, e.g. 'BTCUSDT'
        variant: 'camarilla' (default) | 'standard' | 'all'
                 - 'camarilla' : Standard P + Camarilla H1..H4 / L1..L4
                 - 'standard'  : P + R1..R3 + S1..S3
                 - 'all'       : both sets merged, P deduplicated
        period:  source candle timeframe — '1d' (previous UTC day, default)
                 or '1w' (previous ISO week)

    Returns:
        List of level dicts:
            {level, label, variant, direction, period, source_open_time}
        Ordered resistance → pivot → support (top to bottom by price).
    """
    fn = _VARIANTS.get(variant)
    if fn is None and variant != 'all':
        raise ValueError(
            f"Unknown pivot variant '{variant}'. "
            f"Expected one of: {sorted(list(_VARIANTS) + ['all'])}"
        )

    prev = _fetch_prev_completed_candle(symbol, period)
    if prev is None:
        return []

    h = float(prev.high)
    l = float(prev.low)
    c = float(prev.close)

    if variant == 'all':
        raw = _standard_levels(h, l, c) + _camarilla_levels(h, l, c)
        # Deduplicate by label (Standard P == Camarilla P); keep first occurrence
        seen, levels = set(), []
        for label, lvl, direction in raw:
            if label in seen:
                continue
            seen.add(label)
            levels.append((label, lvl, direction))
    else:
        levels = fn(h, l, c)

    src_ts = prev.open_time
    if hasattr(src_ts, 'tzinfo') and src_ts.tzinfo is not None:
        src_ts = src_ts.replace(tzinfo=None)
    src_iso = src_ts.isoformat() if src_ts else None

    result = [
        {
            'level': round(float(lvl), 8),
            'label': label,
            'variant': variant,
            'direction': direction,
            'period': period,
            'source_open_time': src_iso,
        }
        for label, lvl, direction in levels
    ]

    # Sort resistance (highest) → pivot → support (lowest) for stable rendering
    result.sort(key=lambda d: d['level'], reverse=True)
    return result
