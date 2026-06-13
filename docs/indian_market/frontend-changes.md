# Frontend Changes

## Overview

The frontend needs a global market toggle (`CRYPTO` ↔ `INDIAN`) that switches the entire app context. All pages, API calls, and components become market-aware through React Context.

## 1. Market Context

### New file: `frontend/src/contexts/MarketContext.tsx`

```tsx
import { createContext, useContext, useState, useEffect } from 'react';

export type MarketType = 'CRYPTO' | 'INDIAN';

interface MarketContextValue {
  marketType: MarketType;
  setMarketType: (type: MarketType) => void;
  toggleMarket: () => void;
}

const MarketContext = createContext<MarketContextValue>({
  marketType: 'CRYPTO',
  setMarketType: () => {},
  toggleMarket: () => {},
});

export function MarketProvider({ children }: { children: React.ReactNode }) {
  const [marketType, setMarketType] = useState<MarketType>(() => {
    return (localStorage.getItem('tbot_market_type') as MarketType) || 'CRYPTO';
  });

  useEffect(() => {
    localStorage.setItem('tbot_market_type', marketType);
  }, [marketType]);

  const toggleMarket = () => {
    setMarketType(prev => prev === 'CRYPTO' ? 'INDIAN' : 'CRYPTO');
  };

  return (
    <MarketContext.Provider value={{ marketType, setMarketType, toggleMarket }}>
      {children}
    </MarketContext.Provider>
  );
}

export const useMarket = () => useContext(MarketContext);
```

### Wrap in `main.tsx`

```tsx
import { MarketProvider } from './contexts/MarketContext';

// Wrap App:
<MarketProvider>
  <App />
</MarketProvider>
```

## 2. App.tsx — Market Toggle

### Sidebar/Header Changes

Add market toggle pill next to the app title:

```tsx
// In AppLayout
import { useMarket } from '../contexts/MarketContext';
import { Coins, Landmark } from 'lucide-react';

function AppLayout() {
  const { marketType, setMarketType } = useMarket();

  const marketColors = {
    CRYPTO: { bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/50' },
    INDIAN: { bg: 'bg-orange-500/20', text: 'text-orange-400', border: 'border-orange-500/50' },
  };

  const titles = {
    CRYPTO: 'Crypto Signals',
    INDIAN: 'Indian Markets',
  };

  // In sidebar:
  <div className="p-4 text-xl font-bold border-b border-slate-700">
    <span className={marketColors[marketType].text}>{titles[marketType]}</span>
  </div>

  {/* Market Toggle */}
  <div className="px-4 py-3 border-b border-slate-700">
    <div className="flex bg-slate-700/50 rounded-lg p-0.5">
      <button
        onClick={() => setMarketType('CRYPTO')}
        className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-md text-xs font-medium transition ${
          marketType === 'CRYPTO'
            ? 'bg-emerald-500/30 text-emerald-400'
            : 'text-slate-400 hover:text-slate-300'
        }`}
      >
        <Coins size={14} />
        Crypto
      </button>
      <button
        onClick={() => setMarketType('INDIAN')}
        className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-md text-xs font-medium transition ${
          marketType === 'INDIAN'
            ? 'bg-orange-500/30 text-orange-400'
            : 'text-slate-400 hover:text-slate-300'
        }`}
      >
        <Landmark size={14} />
        Indian
      </button>
    </div>
  </div>
```

### Market Hours Indicator

Add below the toggle only when Indian market is selected:
```tsx
{marketType === 'INDIAN' && <MarketStatusBadge />}
```

New component `MarketStatusBadge`:
```tsx
function MarketStatusBadge() {
  const [isOpen, setIsOpen] = useState(false);
  useEffect(() => {
    apiClient.get('/market/status').then(res => {
      setIsOpen(res.data.indian.is_open);
    });
    const interval = setInterval(() => {
      apiClient.get('/market/status').then(res => {
        setIsOpen(res.data.indian.is_open);
      });
    }, 60000); // every minute
    return () => clearInterval(interval);
  }, []);

  return (
    <div className={`px-4 py-2 text-xs flex items-center gap-2 ${
      isOpen ? 'text-green-400' : 'text-red-400'
    }`}>
      <div className={`w-2 h-2 rounded-full ${isOpen ? 'bg-green-400' : 'bg-red-400'}`} />
      {isOpen ? 'Market Open' : 'Market Closed'}
    </div>
  );
}
```

## 3. SignalFeed Page

File: `frontend/src/pages/SignalFeed/SignalFeed.tsx`

### Changes

1. Import and use `useMarket()`:
```tsx
const { marketType } = useMarket();
```

2. Pass `marketType` to API calls:
```tsx
useEffect(() => {
  apiClient.get('/signals/watching', { params: { market_type: marketType } })
    .then(res => setWatchingSetups(res.data.setups || []));
  apiClient.get('/signals/confirmed', { params: { market_type: marketType } })
    .then(res => setConfirmedSignals(res.data.signals || []));
  apiClient.get('/signals/rejected', { params: { market_type: marketType } })
    .then(res => setRejectedSignals(res.data.signals || []));
}, [marketType]);
```

3. Filter SSE events by market type:
```tsx
const handleSSEEvent = useCallback((eventType, data) => {
  // Only process events matching the active market type
  if (data.market_type && data.market_type !== marketType) return;
  // ... rest of handler
}, [marketType, setSessions]);
```

4. Quick Start adapts to market:
```tsx
const handleQuickStart = useCallback(async () => {
  if (marketType === 'CRYPTO') {
    // Existing BTC/ETH/SOL quick start
    await handleStartSession('BTCUSDT', selectedStratNames, timeframes);
    // ...
  } else {
    // Indian quick start: NIFTY, BANKNIFTY, RELIANCE, TCS
    for (const sym of ['NIFTY', 'BANKNIFTY', 'RELIANCE']) {
      await handleStartSession(sym, selectedStratNames, ['5m', '15m', '1h'], 'INDIAN');
    }
  }
}, [marketType, ...]);
```

## 4. SessionPanel

File: `frontend/src/pages/SignalFeed/SessionPanel.tsx`

### Market-aware symbol selector

```tsx
import { useMarket } from '../../contexts/MarketContext';

const CRYPTO_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT'];
const INDIAN_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'SENSEX', 'FINNIFTY', 
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'ITC'];

function SessionPanel({ ... }) {
  const { marketType } = useMarket();
  const symbols = marketType === 'CRYPTO' ? CRYPTO_SYMBOLS : INDIAN_SYMBOLS;
  
  // Symbol selector:
  <select value={symbol} onChange={e => setSymbol(e.target.value)}>
    {symbols.map(sym => <option key={sym} value={sym}>{sym}</option>)}
  </select>
  
  // Or for Indian market: searchable dropdown / combobox for 1900+ stocks
  // For MVP, use a select with top 20 stocks + index futures/options
}
```

### Market-aware timeframes

```tsx
const CRYPTO_TIMEFRAMES = ['5m', '15m', '30m', '1h', '4h', '1d'];
const INDIAN_TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '1d'];
// No 4h for Indian (market is only 6h 15min)

const availableTimeframes = marketType === 'CRYPTO' ? CRYPTO_TIMEFRAMES : INDIAN_TIMEFRAMES;
```

### Start session with market type

```tsx
const handleStart = () => {
  onStartSession(symbol.toUpperCase(), selectedStrategies, selectedTimeframes, marketType);
  // ...
};
```

## 5. Signal Cards — Market Badge

### WatchingCard (`components/WatchingCard/WatchingCard.tsx`)

Add a market badge in the card header:
```tsx
<div className="flex items-center gap-2">
  <span className="font-bold">{setup.symbol}</span>
  <MarketBadge type={setup.market_type} />
</div>
```

### MarketBadge component (new)

```tsx
function MarketBadge({ type }: { type: MarketType }) {
  if (type === 'INDIAN') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/30">
        INDIAN
      </span>
    );
  }
  return null; // Crypto is default, no badge needed (or green badge if preferred)
}
```

Same pattern for `ConfirmedCard` and `RejectedCard`.

## 6. Charts Page

File: `frontend/src/pages/Charts/Charts.tsx`

- Symbol selector becomes market-aware
- Fetch candles with `market_type` param:
```tsx
const { data } = await apiClient.get('/data/candles', {
  params: { symbol, timeframe, limit, market_type: marketType },
});
```

## 7. Historical Data Page

File: `frontend/src/pages/HistoricalData/HistoricalData.tsx`

Add tabs or a toggle:
```
[Binance (Crypto)] [Angel One (Indian)]
```

Indian tab shows:
- Symbol selector for Indian stocks/indices
- Timeframe selector (Indian-compatible)
- Date range (must align with market hours)
- "Import from Angel One" button

## 8. Types Updates

File: `frontend/src/types/signals.ts`

```ts
export type MarketType = 'CRYPTO' | 'INDIAN';

export interface AnalysisSession {
  session_id: string;
  symbol: string;
  strategy_names: string[];
  timeframes: string[];
  status: 'active' | 'stopping' | 'stopped';
  market_type: MarketType;        // NEW
  created_at: string;
  live_price: number | null;
  live_price_updated_at: string | null;
}

export interface WatchingSetup {
  // ... existing
  market_type: MarketType;        // NEW
}

export interface ConfirmedSignal {
  // ... existing
  market_type: MarketType;        // NEW
}

export interface RejectedSignal {
  // ... existing
  market_type: MarketType;        // NEW
}
```

## 9. API Client Updates

File: `frontend/src/api/client.ts`

```ts
import { MarketType } from '../types/signals';

export const startSession = async (
  symbol: string,
  strategyNames: string[],
  timeframes?: string[],
  marketType: MarketType = 'CRYPTO',
): Promise<AnalysisSession> => {
  const { data } = await apiClient.post('/signals/sessions', {
    symbol,
    strategy_names: strategyNames,
    timeframes,
    market_type: marketType,
  });
  return data.session;
};

// New: Indian instrument search
export const searchIndianInstruments = async (query: string) => {
  const { data } = await apiClient.get('/market/instruments', {
    params: { q: query, market_type: 'INDIAN' },
  });
  return data.instruments;
};

// New: Market status
export const fetchMarketStatus = async () => {
  const { data } = await apiClient.get('/market/status');
  return data;
};

// New: Option chain
export const fetchOptionChain = async (symbol: string, expiry: string) => {
  const { data } = await apiClient.get('/market/option-chain', {
    params: { symbol, expiry },
  });
  return data.chain;
};
```
