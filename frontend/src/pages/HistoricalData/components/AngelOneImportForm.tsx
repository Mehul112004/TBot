import React, { useState } from 'react';
import { DownloadCloud, Loader2 } from 'lucide-react';
import { importAngelOneData } from '../../../api/client';

export default function AngelOneImportForm({ onSuccess }: { onSuccess: () => void }) {
  const [symbol, setSymbol] = useState('NIFTY');
  const [timeframe, setTimeframe] = useState('1h');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{type: 'success'|'error', text: string} | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setStatusMsg(null);
    try {
      const start = new Date(startDate);
      const end = new Date(endDate);
      
      // Calculate diff in days
      const diffTime = Math.abs(end.getTime() - start.getTime());
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)); 

      // Rate limiting protections / data limitations
      if (end < start) {
        throw new Error("End date must be after start date.");
      }
      
      if (timeframe !== '1d' && diffDays > 30) {
        throw new Error("Cannot fetch more than 30 days of intraday data at once to respect rate limits.");
      }
      if (timeframe === '1d' && diffDays > 365 * 2) {
        throw new Error("Cannot fetch more than 2 years of daily data at once.");
      }

      const startIso = start.toISOString();
      const endIso = end.toISOString();
      
      const result = await importAngelOneData({
        symbol,
        timeframe,
        start_time: startIso,
        end_time: endIso
      });
      setStatusMsg({ type: 'success', text: `Imported ${result.count} candles successfully.`});
      onSuccess();
    } catch (err: any) {
      console.error(err);
      setStatusMsg({ type: 'error', text: err.response?.data?.error || err.message || 'Failed to import data.' });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label className="block text-xs font-semibold text-slate-400 mb-1">Symbol</label>
        <select 
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-orange-500"
        >
          <option value="NIFTY">NIFTY</option>
          <option value="BANKNIFTY">BANKNIFTY</option>
          <option value="RELIANCE">RELIANCE</option>
          <option value="HDFCBANK">HDFCBANK</option>
          <option value="TCS">TCS</option>
          <option value="INFY">INFY</option>
        </select>
      </div>

      <div>
        <label className="block text-xs font-semibold text-slate-400 mb-1">Timeframe</label>
        <select 
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value)}
          className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-orange-500"
        >
          <option value="1m">1m</option>
          <option value="5m">5m</option>
          <option value="15m">15m</option>
          <option value="30m">30m</option>
          <option value="1h">1h</option>
          <option value="1d">1d</option>
        </select>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1">Start Date</label>
          <input 
            type="datetime-local" 
            required
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-orange-500"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1">End Date</label>
          <input 
            type="datetime-local" 
            required
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-orange-500"
          />
        </div>
      </div>

      {statusMsg && (
        <div className={`p-3 rounded-lg text-sm flex items-center gap-2 ${
          statusMsg.type === 'success' ? 'bg-orange-900/40 text-orange-400' : 'bg-red-900/40 text-red-400'
        }`}>
          {statusMsg.text}
        </div>
      )}

      <button
        type="submit"
        disabled={isLoading}
        className="w-full mt-4 flex items-center justify-center space-x-2 bg-orange-600 hover:bg-orange-500 text-white font-semibold py-2.5 px-4 rounded-lg transition disabled:opacity-50"
      >
        {isLoading ? (
          <Loader2 size={18} className="animate-spin" />
        ) : (
          <DownloadCloud size={18} />
        )}
        <span>{isLoading ? 'Fetching Data...' : 'Start Job'}</span>
      </button>
    </form>
  );
}
