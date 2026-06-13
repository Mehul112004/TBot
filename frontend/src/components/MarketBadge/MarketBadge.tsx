import type { MarketType } from '../../contexts/MarketContext';

interface MarketBadgeProps {
  type: MarketType;
}

export default function MarketBadge({ type }: MarketBadgeProps) {
  if (type === 'INDIAN') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/30 flex-shrink-0">
        NSE
      </span>
    );
  }
  return null;
}
