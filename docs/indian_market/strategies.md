# Indian Market Strategies

## Overview

Indian market strategies differ from crypto strategies in key ways:
- **Market hours**: Only 6h 15min (9:15–15:30 IST), so intraday patterns are compressed
- **Pre-open session**: 9:00–9:15 AM for price discovery
- **Circuit breakers**: Stocks can hit upper/lower circuits (no trading beyond)
- **F&O expiry dynamics**: Weekly expiry on Thursdays for BankNifty, monthly for Nifty
- **Index weightage**: Heavyweights (RELIANCE, HDFCBANK, INFY) move the index
- **FII/DII flows**: Institutional activity drives sentiment
- **V-shaped recoveries**: Common in Indian markets post-opening selloffs

## Strategy Design Pattern

All strategies inherit from `BaseStrategy` and follow the gate-based confidence framework. They are market-type-aware and declare `allowed_market_types`.

```python
class IndianIntradayStrategy(BaseStrategy):
    allowed_market_types = ['INDIAN']
    # Only runs for Indian market sessions
```

## Strategy 1: Opening Range Breakout (ORB)

**File:** `backend/app/strategies/indian_orb.py`

**Concept:** The first 15-minute candle (9:15–9:30) defines the opening range. A breakout above or below this range signals intraday momentum.

**Timeframe:** 15m (primary), 5m (confirmation)
**Regimes:** TRENDING_UP, TRENDING_DOWN
**Min Confidence:** 0.60

**Gates:**

| # | Type | Description |
|---|---|---|
| G1 | HARD | First 15m candle range identified (opening range high/low set) |
| G2 | HARD | Price breaks above OR high (LONG) or below OR low (SHORT) |
| G3 | HARD | Volume on breakout candle > 1.5x 15-period moving average |
| G4 | SOFT | Breakout direction aligns with pre-market trend (gap direction) |
| G5 | SOFT | ADX > 20 (momentum supporting) |
| G6 | SOFT | Price not near prior day high/low (no immediate resistance) |
| G7 | SOFT | RSI not overbought (>70 for LONG) / not oversold (<30 for SHORT) |

**Entry:** Next 15m candle open after breakout
**SL:** Opposite side of the opening range + ATR buffer
**TP1:** 1x range distance from entry
**TP2:** 2x range distance from entry

**Required features:** `['ema', 'rsi', 'adx', 'volume_ma']`

---

## Strategy 2: VWAP Mean Reversion

**File:** `backend/app/strategies/indian_vwap_reversal.py`

**Concept:** Stocks trending far from VWAP (Volume-Weighted Average Price) tend to revert. This strategy fades extended moves with confirmation.

**Timeframe:** 5m
**Regimes:** RANGING, CHOPPY (runs in non-trending markets)
**Min Confidence:** 0.65

**Gates:**

| # | Type | Description |
|---|---|---|
| G1 | HARD | Price deviation from VWAP > 2% (equity) or > 0.5% (index) |
| G2 | HARD | RSI confirms extreme: > 75 (short signal) or < 25 (long signal) |
| G3 | HARD | Candle pattern shows reversal: doji, hammer, shooting star, engulfing |
| G4 | SOFT | Price is at/near known S/R level (confluence with structural zone) |
| G5 | SOFT | Volume declining (exhaustion, not continuation) |
| G6 | SOFT | Time of day: not last 30 minutes (avoid closing volatility) |

**Entry:** Market order at current candle close
**SL:** Recent swing + ATR
**TP1:** VWAP line itself
**TP2:** 1.5x distance from entry to VWAP on the other side

**Required features:** `['rsi', 'atr', 'volume_ma', 'sr']`
**New feature needed:** `vwap` — compute VWAP resets at 9:15 AM daily

---

## Strategy 3: Gap Fill Strategy

**File:** `backend/app/strategies/indian_gap_fill.py`

**Concept:** Indian stocks often gap up/down at open and fill the gap within the first hour. This trades the gap-fill direction.

**Timeframe:** 5m
**Regimes:** All (but only runs first 60 minutes)
**Min Confidence:** 0.55

**Gates:**

| # | Type | Description |
|---|---|---|
| G1 | HARD | Gap detected: open price differs from prior close by > 1% |
| G2 | HARD | First 2 candles (10 min) confirm gap direction (not immediate reversal) |
| G3 | HARD | Gap size < 3% (too large = likely news-driven, avoid) |
| G4 | SOFT | Prior day was trending (gap continuation more probable) |
| G5 | SOFT | Index also gapped in same direction (broad market confirmation) |
| G6 | SOFT | Volume > average in first 15 minutes (participation) |

**Entry:** After confirmation candles, in gap-fill direction
**SL:** Beyond the opening high/low of the day
**TP1:** 50% gap fill
**TP2:** 100% gap fill (prior day close)

**Required features:** `['ema', 'atr', 'volume_ma', 'adx']`
**New feature:** `prior_close`, `day_open`, `gap_pct` — computed from prior day final candle

---

## Strategy 4: Option Greeks-Based Entry

**File:** `backend/app/strategies/indian_option_greeks.py`

**Concept:** Trade Nifty/BankNifty options based on IV percentile, PCR, and delta/gamma dynamics. Targets ATM/OTM strikes with favorable risk-reward.

**Timeframe:** 5m for index price, 1d for option metrics
**Regimes:** TRENDING_UP, TRENDING_DOWN
**Min Confidence:** 0.70

> **Note:** This strategy requires option chain data. It's more complex and recommended for Phase E (iteration after MVP).

**Gates:**

| # | Type | Description |
|---|---|---|
| G1 | HARD | Market regime confirmed (ADX > 25 and directional) |
| G2 | HARD | IV Percentile between 20-80 (neither too low nor extreme) |
| G3 | HARD | PCR (Put-Call Ratio) confirms direction: < 0.7 bullish, > 1.3 bearish |
| G4 | SOFT | Option delta > 0.30 (LONG call) or > 0.30 (LONG put) — meaningful exposure |
| G5 | SOFT | Theta decay low (> 3 DTE) — not fighting expiry decay |
| G6 | SOFT | India VIX trending down (volatility contraction = favorable for directional) |

**Entry:** Limit order at option bid-ask mid
**SL:** Based on option price (e.g., 30% of premium)
**TP:** Based on underlying move (1% for index options = significant option % gain)

**Required features:** `['ema', 'rsi', 'atr', 'adx', 'sr']`
**New features:** `iv_percentile`, `pcr`, `option_greeks`, `india_vix`

---

## Adapting Existing Crypto Strategies

Most existing strategies can work for Indian markets with parameter tuning:

| Crypto Strategy | Indian Adaptation | Changes |
|---|---|---|
| **Trend Following** | Works on 15m/1h for Nifty/RELIANCE | Reduce ATR multiplier (Indian ATRs are smaller relative to price) |
| **Breakout & Retest** | Works on 30m/1h for BankNifty | Add circuit-breaker gate (if price near circuit, skip) |
| **Key Level Reversal** | Works on 5m/15m for stocks | Add time-of-day gate (skip last 30 min) |
| **Liquidity Sweep** | Works on 15m for indices | Adjust SL placement (Indian market has narrower stops) |
| **Burner 9/20** | Minimal changes | EMA period adaptation for compressed day |
| **EMA Cross Alert** | Works as-is | Simple alert generation |

### Parameter Tuning Constants

```python
# In config.py — Indian market adaptations
INDIAN_STRATEGY_OVERRIDES = {
    'Trend Following': {
        'sl_atr_mult': 1.2,      # From 1.5 (tighter SL for Indian)
        'min_confidence': 0.50,  # From 0.55 (slightly relaxed)
    },
    'Breakout & Retest': {
        'sl_atr_mult': 1.0,
        'min_confidence': 0.50,
    },
    'Key Level Reversal': {
        'min_confidence': 0.65,  # From 0.70
    },
}
```

## Strategy Selection by Market Type

In `strategy_loader.py`, strategies can declare their supported markets:

```python
class BaseStrategy(ABC):
    allowed_market_types: List[str] = ['CRYPTO']  # Default: crypto only
    # Set to ['INDIAN'] or ['CRYPTO', 'INDIAN'] for cross-market strategies
```

The registry filters:
```python
def get_strategies_for_market(self, market_type: str) -> List[BaseStrategy]:
    return [s for s in self._strategies.values() 
            if market_type in s.allowed_market_types]
```

## LLM Context for Indian Market

The `llm_context_builder.py` needs Indian-specific additions:
- Market session phase (opening rush / mid-day drift / closing volatility)
- India VIX level
- FII/DII net flows (if available from NSE data)
- Option expiry proximity (days to expiry)
- Circuit levels for the stock
