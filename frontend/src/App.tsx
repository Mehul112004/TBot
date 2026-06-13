import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import HistoricalData from './pages/HistoricalData/HistoricalData';
import SignalFeed from './pages/SignalFeed/SignalFeed';
import Backtest from './pages/Backtest/Backtest';
import BacktestAnalyser from './pages/BacktestAnalyser/BacktestAnalyser';
import Charts from './pages/Charts/Charts';
import LLMPrompts from './pages/LLMPrompts/LLMPrompts';
import PriceAlerts from './pages/PriceAlerts/PriceAlerts';
import { LineChart, LayoutDashboard, History, Bot, CandlestickChart, Menu, X, Bell, FileSearch, Coins, Landmark } from 'lucide-react';
import { useMarket } from './contexts/MarketContext';

function NavLink({ to, icon: Icon, label }: { to: string; icon: React.ElementType; label: string }) {
  const location = useLocation();
  const isActive = location.pathname === to;

  return (
    <Link
      to={to}
      className={`flex items-center space-x-3 p-2 rounded-lg transition ${
        isActive
          ? 'text-emerald-400 bg-slate-700/50 border border-slate-600'
          : 'text-slate-300 hover:text-white hover:bg-slate-700'
      }`}
    >
      <Icon size={20} />
      <span>{label}</span>
    </Link>
  );
}

function AppLayout() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const location = useLocation();
  const { marketType, setMarketType } = useMarket();

  useEffect(() => {
    setIsMobileMenuOpen(false);

    const titles: Record<string, string> = {
      '/': `Historical Data | ${marketType === 'INDIAN' ? 'Indian Markets' : 'Crypto Signals'}`,
      '/signal-feed': `Signal Feed | ${marketType === 'INDIAN' ? 'Indian Markets' : 'Crypto Signals'}`,
      '/charts': `Charts | ${marketType === 'INDIAN' ? 'Indian Markets' : 'Crypto Signals'}`,
      '/backtest': `Backtest Engine | ${marketType === 'INDIAN' ? 'Indian Markets' : 'Crypto Signals'}`,
      '/backtest-analyser': `Backtest Analyser | ${marketType === 'INDIAN' ? 'Indian Markets' : 'Crypto Signals'}`,
      '/llm-prompts': `LLM Prompts | ${marketType === 'INDIAN' ? 'Indian Markets' : 'Crypto Signals'}`,
      '/price-alerts': `Price Alerts | ${marketType === 'INDIAN' ? 'Indian Markets' : 'Crypto Signals'}`,
    };
    document.title = titles[location.pathname] || 'Trading Bot';
  }, [location.pathname, marketType]);

  const accentColor = marketType === 'INDIAN' ? 'text-orange-400' : 'text-emerald-400';
  const titleText = marketType === 'INDIAN' ? 'Indian Markets' : 'Crypto Signals';

  return (
    <div className="flex flex-col md:flex-row h-screen bg-slate-900 text-white overflow-hidden">
      {/* Mobile Top Bar */}
      <header className="md:hidden flex items-center justify-between p-4 bg-slate-800 border-b border-slate-700 z-20 flex-shrink-0">
        <span className={`text-xl font-bold ${accentColor}`}>{titleText}</span>
        <button
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-700 focus:outline-none"
        >
          {isMobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      </header>

      {/* Sidebar - Desktop */}
      <aside className="hidden md:flex w-64 bg-slate-800 border-r border-slate-700 flex-col flex-shrink-0">
        <div className={`p-4 text-xl font-bold border-b border-slate-700 ${accentColor}`}>
          {titleText}
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

        <nav className="flex-1 p-4 space-y-2">
          <NavLink to="/signal-feed" icon={LayoutDashboard} label="Signal Feed" />
          <NavLink to="/charts" icon={CandlestickChart} label="Charts" />
          <NavLink to="/backtest" icon={LineChart} label="Backtest Engine" />
          <NavLink to="/backtest-analyser" icon={FileSearch} label="Backtest Analyser" />
          <NavLink to="/" icon={History} label="Historical Data" />
          <NavLink to="/llm-prompts" icon={Bot} label="LLM Prompts" />
          <NavLink to="/price-alerts" icon={Bell} label="Price Alerts" />
        </nav>
      </aside>

      {/* Mobile Sidebar Overlay/Drawer */}
      {isMobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-30 flex">
          <div
            className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm"
            onClick={() => setIsMobileMenuOpen(false)}
          />
          <aside className="relative flex flex-col w-64 max-w-xs bg-slate-800 border-r border-slate-700 h-full p-4 space-y-4">
            <div className={`text-xl font-bold pb-4 border-b border-slate-700 ${accentColor}`}>
              {titleText}
            </div>

            {/* Mobile Market Toggle */}
            <div className="py-2 border-b border-slate-700">
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

            <nav className="flex-1 space-y-2">
              <NavLink to="/signal-feed" icon={LayoutDashboard} label="Signal Feed" />
              <NavLink to="/charts" icon={CandlestickChart} label="Charts" />
              <NavLink to="/backtest" icon={LineChart} label="Backtest Engine" />
              <NavLink to="/backtest-analyser" icon={FileSearch} label="Backtest Analyser" />
              <NavLink to="/" icon={History} label="Historical Data" />
              <NavLink to="/llm-prompts" icon={Bot} label="LLM Prompts" />
              <NavLink to="/price-alerts" icon={Bell} label="Price Alerts" />
            </nav>
          </aside>
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 overflow-hidden bg-slate-900">
        <Routes>
          <Route path="/" element={<HistoricalData />} />
          <Route path="/signal-feed" element={<SignalFeed />} />
          <Route path="/charts" element={<Charts />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/backtest-analyser" element={<BacktestAnalyser />} />
          <Route path="/llm-prompts" element={<LLMPrompts />} />
          <Route path="/price-alerts" element={<PriceAlerts />} />
        </Routes>
      </main>
    </div>
  );
}

function App() {
  return (
    <Router>
      <AppLayout />
    </Router>
  );
}

export default App;
