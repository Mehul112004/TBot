import { useState, useEffect, useCallback } from "react";
import { Plus, X, Trash2, Bell, BellOff } from "lucide-react";
import { fetchAlerts, createAlert, deleteAlert } from "../../api/client";
import type { PriceAlert } from "../../types/alerts";

const AVAILABLE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"];

export default function PriceAlerts() {
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [targetPrice, setTargetPrice] = useState("");
  const [direction, setDirection] = useState<"ABOVE" | "BELOW">("ABOVE");
  const [alertType, setAlertType] = useState<"ONCE" | "EVERY_TIME">("ONCE");
  const [note, setNote] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  const loadAlerts = useCallback(() => {
    fetchAlerts().then((data) => setAlerts(data.alerts)).catch(() => {});
  }, []);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  const handleCreate = async () => {
    if (!symbol || !targetPrice) return;
    setError("");
    setIsSubmitting(true);
    try {
      await createAlert({
        symbol: symbol.toUpperCase(),
        target_price: parseFloat(targetPrice),
        direction,
        alert_type: alertType,
        note: note || undefined,
      });
      setShowForm(false);
      setSymbol("BTCUSDT");
      setTargetPrice("");
      setDirection("ABOVE");
      setAlertType("ONCE");
      setNote("");
      loadAlerts();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? (e as { response?: { data?: { error?: string } } }).response?.data
              ?.error || "Failed to create alert"
          : "Failed to create alert";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancel = async (alertId: string) => {
    try {
      await deleteAlert(alertId);
      loadAlerts();
    } catch {
      // ignore
    }
  };

  const activeAlerts = alerts.filter((a) => a.status === "ACTIVE");
  const triggeredAlerts = alerts.filter((a) => a.status === "TRIGGERED");
  const cancelledAlerts = alerts.filter((a) => a.status === "CANCELLED");

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 p-4 md:p-6 border-b border-slate-700/50">
        <div className="flex justify-between items-center">
          <h1 className="font-bold text-xl text-white">Price Alerts</h1>
          {!showForm && (
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 px-3 py-1.5 rounded-lg font-medium text-white text-xs transition"
            >
              <Plus size={14} />
              New Alert
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
        {/* Create Form */}
        {showForm && (
          <div className="bg-slate-800/80 backdrop-blur-sm p-4 border border-slate-600/50 rounded-xl">
            <div className="flex justify-between items-center mb-3">
              <h3 className="font-semibold text-sm text-white">
                New Price Alert
              </h3>
              <button
                onClick={() => {
                  setShowForm(false);
                  setError("");
                }}
                className="text-slate-400 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>

            {error && (
              <div className="mb-3 bg-red-500/10 px-3 py-2 border border-red-500/30 rounded-lg text-red-400 text-xs">
                {error}
              </div>
            )}

            {/* Symbol */}
            <div className="mb-3">
              <label className="block mb-1 text-slate-400 text-xs">
                Trading Pair
              </label>
              <select
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                className="bg-slate-700 px-3 py-2 border border-slate-600 focus:border-emerald-500 rounded-lg w-full text-sm text-white transition placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 appearance-none"
              >
                {AVAILABLE_SYMBOLS.map((sym) => (
                  <option key={sym} value={sym}>
                    {sym}
                  </option>
                ))}
              </select>
            </div>

            {/* Target Price */}
            <div className="mb-3">
              <label className="block mb-1 text-slate-400 text-xs">
                Target Price (USD)
              </label>
              <input
                type="number"
                step="any"
                value={targetPrice}
                onChange={(e) => setTargetPrice(e.target.value)}
                placeholder="e.g. 95000"
                className="bg-slate-700 px-3 py-2 border border-slate-600 focus:border-emerald-500 rounded-lg w-full font-mono text-sm text-white transition placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </div>

            {/* Direction */}
            <div className="mb-3">
              <label className="block mb-1 text-slate-400 text-xs">
                Alert Direction
              </label>
              <div className="flex gap-2">
                {(["ABOVE", "BELOW"] as const).map((d) => (
                  <button
                    key={d}
                    onClick={() => setDirection(d)}
                    className={`flex-1 text-xs px-2.5 py-2 rounded-lg border transition font-medium ${
                      direction === d
                        ? d === "ABOVE"
                          ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-400"
                          : "bg-red-500/20 border-red-500/50 text-red-400"
                        : "bg-slate-700/50 border-slate-600/50 text-slate-400 hover:border-slate-500"
                    }`}
                  >
                    {d === "ABOVE" ? "Above" : "Below"}
                  </button>
                ))}
              </div>
            </div>

            {/* Alert Type */}
            <div className="mb-3">
              <label className="block mb-1 text-slate-400 text-xs">
                Alert Type
              </label>
              <div className="flex gap-2">
                {(["ONCE", "EVERY_TIME"] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setAlertType(t)}
                    className={`flex-1 text-xs px-2.5 py-2 rounded-lg border transition font-medium ${
                      alertType === t
                        ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-400"
                        : "bg-slate-700/50 border-slate-600/50 text-slate-400 hover:border-slate-500"
                    }`}
                  >
                    {t === "ONCE" ? "Once" : "Every Time"}
                  </button>
                ))}
              </div>
            </div>

            {/* Note */}
            <div className="mb-4">
              <label className="block mb-1 text-slate-400 text-xs">
                Note (optional)
              </label>
              <input
                type="text"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. breakout confirmation"
                className="bg-slate-700 px-3 py-2 border border-slate-600 focus:border-emerald-500 rounded-lg w-full text-sm text-white transition placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </div>

            {/* Submit */}
            <button
              onClick={handleCreate}
              disabled={!symbol || !targetPrice || isSubmitting}
              className="flex justify-center items-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 py-2 rounded-lg w-full font-medium text-sm text-white transition disabled:cursor-not-allowed"
            >
              <Plus size={14} />
              {isSubmitting ? "Creating..." : "Create Alert"}
            </button>
          </div>
        )}

        {/* Active Alerts */}
        <div>
          <h2 className="mb-3 font-semibold text-base text-white">
            Active Alerts ({activeAlerts.length})
          </h2>
          {activeAlerts.length === 0 ? (
            <div className="py-8 text-center text-slate-500 text-sm">
              <Bell size={24} className="opacity-40 mx-auto mb-2" />
              No active alerts — create one to start tracking prices
            </div>
          ) : (
            <div className="space-y-2">
              {activeAlerts.map((alert) => (
                <AlertCard
                  key={alert.id}
                  alert={alert}
                  onCancel={handleCancel}
                />
              ))}
            </div>
          )}
        </div>

        {/* Triggered Alerts */}
        {triggeredAlerts.length > 0 && (
          <div>
            <h2 className="mb-3 font-semibold text-base text-white">
              Triggered ({triggeredAlerts.length})
            </h2>
            <div className="space-y-2">
              {triggeredAlerts.map((alert) => (
                <div
                  key={alert.id}
                  className="bg-slate-800/50 px-4 py-3 border border-slate-700/50 rounded-xl opacity-60"
                >
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-white">
                          {alert.symbol}
                        </span>
                        <AlertBadge direction={alert.direction} />
                        <span className="font-mono text-xs text-slate-300">
                          ${alert.target_price.toLocaleString()}
                        </span>
                      </div>
                      {alert.note && (
                        <p className="mt-1 text-slate-500 text-xs">
                          {alert.note}
                        </p>
                      )}
                    </div>
                    <span className="text-slate-500 text-xs">
                      {alert.triggered_at
                        ? new Date(alert.triggered_at).toLocaleString()
                        : ""}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Cancelled Alerts */}
        {cancelledAlerts.length > 0 && (
          <div>
            <h2 className="mb-3 font-semibold text-base text-white">
              Cancelled ({cancelledAlerts.length})
            </h2>
            <div className="space-y-2">
              {cancelledAlerts.map((alert) => (
                <div
                  key={alert.id}
                  className="bg-slate-800/50 px-4 py-3 border border-slate-700/50 rounded-xl opacity-50"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-slate-400">
                      {alert.symbol}
                    </span>
                    <AlertBadge direction={alert.direction} />
                    <span className="font-mono text-xs text-slate-500">
                      ${alert.target_price.toLocaleString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AlertBadge({ direction }: { direction: "ABOVE" | "BELOW" }) {
  return (
    <span
      className={`text-xs px-1.5 py-0.5 rounded font-medium ${
        direction === "ABOVE"
          ? "bg-emerald-500/20 text-emerald-400"
          : "bg-red-500/20 text-red-400"
      }`}
    >
      {direction === "ABOVE" ? "Above" : "Below"}
    </span>
  );
}

function AlertCard({
  alert,
  onCancel,
}: {
  alert: PriceAlert;
  onCancel: (id: string) => void;
}) {
  return (
    <div className="flex justify-between items-start bg-slate-800/70 backdrop-blur-sm px-4 py-3 border border-slate-700/50 rounded-xl">
      <div>
        <div className="flex items-center gap-2">
          <span className="font-bold text-sm text-white">{alert.symbol}</span>
          <AlertBadge direction={alert.direction} />
          <span className="font-mono text-xs text-slate-300">
            ${alert.target_price.toLocaleString()}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-slate-500 text-xs">
            {alert.alert_type === "ONCE" ? (
              <>
                <Bell size={10} className="inline mr-1" />
                Once
              </>
            ) : (
              <>
                <BellOff size={10} className="inline mr-1" />
                Every Time
              </>
            )}
          </span>
          {alert.note && (
            <span className="text-slate-500 text-xs truncate max-w-[200px]">
              — {alert.note}
            </span>
          )}
        </div>
      </div>
      <button
        onClick={() => onCancel(alert.id)}
        className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-slate-700 transition flex-shrink-0"
        title="Cancel alert"
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}
