import { useState, useCallback, useEffect } from "react";
import { Eye, CheckCircle, XCircle } from "lucide-react";
import { useSSE } from "../../hooks/useSSE";
import { useAnalysisSessions } from "../../hooks/useAnalysisSessions";
import { useMarket } from "../../contexts/MarketContext";
import SessionPanel from "./SessionPanel";
import WatchingTab from "./WatchingTab";
import ConfirmedTab from "./ConfirmedTab";
import RejectedTab from "./RejectedTab";
import type {
  WatchingSetup,
  ConfirmedSignal,
  RejectedSignal,
  SSEEventType,
  PriceUpdate,
  AnalysisSession,
} from "../../types/signals";
import { apiClient } from "../../api/client";

type Tab = "watching" | "confirmed" | "rejected";

export default function SignalFeed() {
  const [activeTab, setActiveTab] = useState<Tab>("watching");
  const [watchingSetups, setWatchingSetups] = useState<WatchingSetup[]>([]);
  const [confirmedSignals, setConfirmedSignals] = useState<ConfirmedSignal[]>([]);
  const [rejectedSignals, setRejectedSignals] = useState<RejectedSignal[]>([]);
  const { marketType } = useMarket();

  const {
    sessions,
    strategies,
    startSession,
    stopSession,
    isLoading,
    canStartNew,
    setSessions,
  } = useAnalysisSessions(marketType as MarketType);

  // Fetch initial data — re-fetch when market type changes
  useEffect(() => {
    apiClient
      .get("/signals/watching", { params: { market_type: marketType } })
      .then((res) => setWatchingSetups(res.data.setups || []))
      .catch(() => {});

    apiClient
      .get("/signals/confirmed", { params: { market_type: marketType } })
      .then((res) => setConfirmedSignals(res.data.signals || []))
      .catch(() => {});

    apiClient
      .get("/signals/rejected", { params: { market_type: marketType } })
      .then((res) => setRejectedSignals(res.data.signals || []))
      .catch(() => {});
  }, [marketType]);

  // Request notification permissions on load
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  // SSE event handler
  const handleSSEEvent = useCallback(
    (eventType: SSEEventType, data: Record<string, unknown>) => {
      // Filter events by active market type
      const eventMarketType = data.market_type as string | undefined;
      if (eventMarketType && eventMarketType !== marketType) return;

      switch (eventType) {
        case "setup_detected": {
          const setup = data as unknown as WatchingSetup;
          setWatchingSetups((prev) => [setup, ...prev]);

          if (
            "Notification" in window &&
            Notification.permission === "granted"
          ) {
            new Notification("New Setup Detected", {
              body: `${setup.symbol} - ${setup.strategy_name} (${setup.timeframe})`,
            });
          }
          break;
        }
        case "setup_updated": {
          const updated = data as unknown as WatchingSetup;
          setWatchingSetups((prev) =>
            prev.map((s) => (s.id === updated.id ? updated : s)),
          );
          break;
        }
        case "setup_expired": {
          const expired = data as unknown as WatchingSetup;
          setWatchingSetups((prev) =>
            prev.map((s) =>
              s.id === expired.id ? { ...s, status: "EXPIRED" as const } : s,
            ),
          );
          setTimeout(() => {
            setWatchingSetups((prev) =>
              prev.filter((s) => s.id !== expired.id),
            );
          }, 2000);
          break;
        }
        case "session_stopped": {
          const sessionId = (data as Record<string, unknown>).session_id as string;
          setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
          setWatchingSetups((prev) =>
            prev.filter((s) => s.session_id !== sessionId),
          );
          break;
        }
        case "price_update": {
          const price = data as unknown as PriceUpdate;
          setSessions((prev) =>
            prev.map((s) =>
              s.session_id === price.session_id
                ? {
                    ...s,
                    live_price: price.price,
                    live_price_updated_at: price.timestamp,
                  }
                : s,
            ),
          );
          break;
        }
        case "signal_confirmed": {
          const sig = data as unknown as ConfirmedSignal;
          setConfirmedSignals((prev) => {
            if (prev.some((s) => s.id === sig.id)) return prev;
            return [sig, ...prev];
          });
          break;
        }
        case "session_started": {
          const session = data as unknown as AnalysisSession;
          setSessions((prev) => {
            if (prev.some((s) => s.session_id === session.session_id))
              return prev;
            return [session, ...prev];
          });
          break;
        }
        default:
          break;
      }
    },
    [marketType, setSessions],
  );

  const { connected } = useSSE(handleSSEEvent);

  const handleStartSession = useCallback(
    async (sym: string, strats: string[], timeframes?: string[], mt?: string) => {
      try {
        await startSession(sym, strats, timeframes, mt || marketType);
      } catch {
        // Error is handled in the hook
      }
    },
    [startSession, marketType],
  );

  const handleStopSession = useCallback(
    async (sessionId: string) => {
      try {
        await stopSession(sessionId);
      } catch {
        // Error is handled in the hook
      }
    },
    [stopSession],
  );

  const handleQuickStart = useCallback(async () => {
    if (strategies.length === 0) return;
    const allowedStrategies = ["Trend Following", "Burner 9/20", "EMA Cross Alert"];
    const selectedStratNames = strategies
      .map((s) => s.name)
      .filter((name) => allowedStrategies.includes(name));

    if (marketType === 'INDIAN') {
      const timeframes = ["5m", "15m", "1h"];
      try {
        await handleStartSession("NIFTY", selectedStratNames, timeframes, 'INDIAN');
        await handleStartSession("RELIANCE", selectedStratNames, timeframes, 'INDIAN');
      } catch (e) {
        console.error("Indian Quick Start failed", e);
      }
    } else {
      const timeframes = ["5m", "15m", "30m", "1h", "4h", "1d"];
      try {
        await handleStartSession("BTCUSDT", selectedStratNames, timeframes, 'CRYPTO');
        await handleStartSession("ETHUSDT", selectedStratNames, timeframes, 'CRYPTO');
        await handleStartSession("SOLUSDT", selectedStratNames, timeframes, 'CRYPTO');
      } catch (e) {
        console.error("Crypto Quick Start failed", e);
      }
    }
  }, [strategies, handleStartSession, marketType]);

  const watchingCount = watchingSetups.filter(
    (s) => s.status === "WATCHING",
  ).length;

  return (
    <div className="w-full h-full overflow-y-auto">
      <div className="mx-auto p-4 md:p-6 max-w-[1600px]">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row gap-4 justify-between sm:items-center mb-6">
          <div>
            <h1 className="mb-1 font-bold text-2xl text-white">Signal Feed</h1>
            <p className="text-slate-400 text-sm">
              Real-time market scanning — detect setups as they form
            </p>
          </div>
          <button
            onClick={handleQuickStart}
            disabled={isLoading || strategies.length === 0 || !canStartNew}
            className="w-full sm:w-auto bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 shadow-sm px-4 py-2 rounded font-medium text-sm text-white transition disabled:cursor-not-allowed"
          >
            Quick Start ({marketType === 'INDIAN' ? 'NIFTY & RELIANCE' : 'BTC, ETH & SOL'})
          </button>
        </div>

        {/* Session Panel */}
        <SessionPanel
          sessions={sessions}
          strategies={strategies}
          canStartNew={canStartNew}
          isLoading={isLoading}
          connected={connected}
          onStartSession={handleStartSession}
          onStopSession={handleStopSession}
        />

        {/* Tab Navigation */}
        <div className="flex items-center gap-1 mb-6 border-slate-700/50 border-b overflow-x-auto whitespace-nowrap scrollbar-none">
          <button
            onClick={() => setActiveTab("watching")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition flex-shrink-0 ${
              activeTab === "watching"
                ? "border-emerald-500 text-emerald-400"
                : "border-transparent text-slate-400 hover:text-slate-300"
            }`}
          >
            <Eye size={16} />
            Watching
            {watchingCount > 0 && (
              <span className="bg-emerald-500/20 ml-1 px-1.5 py-0.5 rounded-full text-emerald-400 text-xs">
                {watchingCount}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab("confirmed")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition flex-shrink-0 ${
              activeTab === "confirmed"
                ? "border-emerald-500 text-emerald-400"
                : "border-transparent text-slate-400 hover:text-slate-300"
            }`}
          >
            <CheckCircle size={16} />
            Confirmed
          </button>
          <button
            onClick={() => setActiveTab("rejected")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition flex-shrink-0 ${
              activeTab === "rejected"
                ? "border-red-500 text-red-400"
                : "border-transparent text-slate-400 hover:text-slate-300"
            }`}
          >
            <XCircle size={16} />
            Rejected
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === "watching" && <WatchingTab setups={watchingSetups} />}
        {activeTab === "confirmed" && (
          <ConfirmedTab
            signals={confirmedSignals}
            activeSessionIds={sessions.map((s) => s.session_id)}
          />
        )}
        {activeTab === "rejected" && (
          <RejectedTab
            signals={rejectedSignals}
            activeSessionIds={sessions.map((s) => s.session_id)}
          />
        )}
      </div>
    </div>
  );
}
