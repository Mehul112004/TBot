# Database Changes

## Overview

All signal-related tables gain a `market_type` column to distinguish between `CRYPTO` (existing) and `INDIAN` (new) signals. A new `indian_instruments` table maps Angel One numeric tokens to human-readable trading symbols.

## Migration Strategy

- New column: `market_type VARCHAR(10) DEFAULT 'CRYPTO' NOT NULL`
- Existing rows retain `'CRYPTO'` — no data migration needed
- ALTER TABLE statements run in `app/__init__.py` alongside existing migrations
- New table: `indian_instruments` created fresh

## Tables to Alter

### 1. `candles`

Add `market_type` to the composite primary key (since a symbol like "NIFTY" could mean different markets):

```sql
ALTER TABLE candles ADD COLUMN market_type VARCHAR(10) DEFAULT 'CRYPTO';
-- Rebuild PK to include market_type
ALTER TABLE candles DROP CONSTRAINT candles_pkey;
ALTER TABLE candles ADD PRIMARY KEY (symbol, timeframe, open_time, market_type);
```

> **Note:** This is the most invasive migration. Ensure all queries include `market_type` in WHERE clauses after this change. Candidate symbols are already unique across markets, but the PK change future-proofs.

### 2. `watching_setups`

```sql
ALTER TABLE watching_setups ADD COLUMN market_type VARCHAR(10) DEFAULT 'CRYPTO';
CREATE INDEX idx_watching_setups_market_type ON watching_setups(market_type);
```

### 3. `confirmed_signals`

```sql
ALTER TABLE confirmed_signals ADD COLUMN market_type VARCHAR(10) DEFAULT 'CRYPTO';
CREATE INDEX idx_confirmed_signals_market_type ON confirmed_signals(market_type);
```

### 4. `rejected_signals`

```sql
ALTER TABLE rejected_signals ADD COLUMN market_type VARCHAR(10) DEFAULT 'CRYPTO';
CREATE INDEX idx_rejected_signals_market_type ON rejected_signals(market_type);
```

### 5. `analysis_sessions`

```sql
ALTER TABLE analysis_sessions ADD COLUMN market_type VARCHAR(10) DEFAULT 'CRYPTO';
CREATE INDEX idx_analysis_sessions_market_type ON analysis_sessions(market_type);
```

### 6. `backtest_runs`

```sql
ALTER TABLE backtest_runs ADD COLUMN market_type VARCHAR(10) DEFAULT 'CRYPTO';
CREATE INDEX idx_backtest_runs_market_type ON backtest_runs(market_type);
```

### 7. `price_alerts`

```sql
ALTER TABLE price_alerts ADD COLUMN market_type VARCHAR(10) DEFAULT 'CRYPTO';
CREATE INDEX idx_price_alerts_market_type ON price_alerts(market_type);
```

### 8. `llm_prompt_logs`

```sql
ALTER TABLE llm_prompt_logs ADD COLUMN market_type VARCHAR(10) DEFAULT 'CRYPTO';
```

### 9. `sr_zones`

```sql
ALTER TABLE sr_zones ADD COLUMN market_type VARCHAR(10) DEFAULT 'CRYPTO';
-- Update unique constraint
ALTER TABLE sr_zones DROP CONSTRAINT uq_sr_zone;
ALTER TABLE sr_zones ADD CONSTRAINT uq_sr_zone UNIQUE (symbol, timeframe, price_level, detection_method, market_type);
```

## New Table: `indian_instruments`

```sql
CREATE TABLE indian_instruments (
    token VARCHAR(20) PRIMARY KEY,                    -- Angel One numeric token
    symbol VARCHAR(100) NOT NULL,                     -- Trading symbol (e.g., "NIFTY 24JUN22400CE")
    name VARCHAR(200),                                -- Display name
    exchange VARCHAR(10) NOT NULL,                    -- NSE, NFO, BSE, BFO
    instrument_type VARCHAR(20) NOT NULL,             -- EQUITY, FUTIDX, OPTIDX, FUTSTK, OPTSTK
    lot_size INTEGER DEFAULT 1,
    expiry DATE,                                      -- NULL for equities
    strike_price DOUBLE PRECISION,                     -- NULL for non-options
    tick_size DOUBLE PRECISION DEFAULT 0.05,
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_instruments_exchange ON indian_instruments(exchange);
CREATE INDEX idx_instruments_type ON indian_instruments(instrument_type);
CREATE INDEX idx_instruments_symbol ON indian_instruments(symbol);
CREATE INDEX idx_instruments_expiry ON indian_instruments(expiry);
```

## SQLAlchemy Model Changes

File: `backend/app/models/db.py`

### Add `market_type` column to all models

Every model gets:
```python
market_type = db.Column(db.String(10), default='CRYPTO', nullable=False, index=True)
```

The `Candle` model's `to_dict()` and composite PK need updating:
```python
class Candle(db.Model):
    __tablename__ = 'candles'
    symbol = db.Column(db.String(50), primary_key=True)
    timeframe = db.Column(db.String(10), primary_key=True)
    open_time = db.Column(db.DateTime(timezone=True), primary_key=True)
    market_type = db.Column(db.String(10), primary_key=True, default='CRYPTO')
    # ... rest unchanged
```

### New model: `IndianInstrument`

```python
class IndianInstrument(db.Model):
    __tablename__ = 'indian_instruments'
    
    token = db.Column(db.String(20), primary_key=True)
    symbol = db.Column(db.String(100), nullable=False, index=True)
    name = db.Column(db.String(200))
    exchange = db.Column(db.String(10), nullable=False, index=True)
    instrument_type = db.Column(db.String(20), nullable=False, index=True)
    lot_size = db.Column(db.Integer, default=1)
    expiry = db.Column(db.Date, nullable=True, index=True)
    strike_price = db.Column(db.Float, nullable=True)
    tick_size = db.Column(db.Float, default=0.05)
    last_updated = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
```

## Query Impact

All candle/signal queries must now filter by `market_type`:

```python
# Before
Candle.query.filter_by(symbol=symbol, timeframe=tf).all()

# After
Candle.query.filter_by(symbol=symbol, timeframe=tf, market_type=market_type).all()
```

The `get_finalized_candles()` utility in `data_utils.py` must accept and propagate `market_type`.

## Rollback Plan

```sql
-- Drop market_type column from each table if rollback needed
ALTER TABLE candles DROP COLUMN market_type;
ALTER TABLE watching_setups DROP COLUMN market_type;
-- ... etc
DROP TABLE indian_instruments;
```
