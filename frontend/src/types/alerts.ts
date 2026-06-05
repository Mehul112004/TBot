export interface PriceAlert {
  id: string;
  symbol: string;
  target_price: number;
  direction: 'ABOVE' | 'BELOW';
  alert_type: 'ONCE' | 'EVERY_TIME';
  status: 'ACTIVE' | 'TRIGGERED' | 'CANCELLED';
  cross_state: string | null;
  note: string;
  created_at: string;
  triggered_at: string | null;
  cancelled_at: string | null;
  updated_at: string | null;
}

export interface PriceAlertCreate {
  symbol: string;
  target_price: number;
  direction: 'ABOVE' | 'BELOW';
  alert_type: 'ONCE' | 'EVERY_TIME';
  note?: string;
}
