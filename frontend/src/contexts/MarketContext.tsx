import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';

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

export function MarketProvider({ children }: { children: ReactNode }) {
  const [marketType, setMarketType] = useState<MarketType>(() => {
    try {
      return (localStorage.getItem('tbot_market_type') as MarketType) || 'CRYPTO';
    } catch {
      return 'CRYPTO';
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('tbot_market_type', marketType);
    } catch {
      // localStorage not available
    }
  }, [marketType]);

  const toggleMarket = () => {
    setMarketType((prev) => (prev === 'CRYPTO' ? 'INDIAN' : 'CRYPTO'));
  };

  return (
    <MarketContext.Provider value={{ marketType, setMarketType, toggleMarket }}>
      {children}
    </MarketContext.Provider>
  );
}

export const useMarket = () => useContext(MarketContext);
