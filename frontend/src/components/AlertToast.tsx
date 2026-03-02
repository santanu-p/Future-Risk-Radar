/** Real-time alert toast — floating notification for threshold breaches.
 *
 * Renders a fixed-position toast stack that auto-dismisses after 8 s.
 */

import { useEffect, useState, useCallback } from "react";
import { useAlertsWS, type AlertPayload } from "../hooks/useWebSocket";

interface ToastItem {
  id: number;
  payload: AlertPayload;
  expiresAt: number;
}

let nextId = 0;

export default function AlertToast() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const handleAlert = useCallback((payload: AlertPayload) => {
    const id = nextId++;
    setToasts((prev) => [
      { id, payload, expiresAt: Date.now() + 8_000 },
      ...prev.slice(0, 4), // max 5 toasts
    ]);
  }, []);

  const { status } = useAlertsWS(handleAlert);

  // Auto-dismiss
  useEffect(() => {
    const timer = setInterval(() => {
      setToasts((prev) => prev.filter((t) => t.expiresAt > Date.now()));
    }, 1_000);
    return () => clearInterval(timer);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-16 right-4 z-50 space-y-2 w-80">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="glass-panel border border-red-500/30 bg-red-500/10 p-3 rounded-lg animate-slide-in-right"
        >
          <div className="flex items-start justify-between">
            <div>
              <div className="text-xs font-semibold text-red-400 uppercase tracking-wider">
                Alert — {toast.payload.region_code}
              </div>
              <div className="mt-1 text-sm text-gray-200">
                {toast.payload.message}
              </div>
              <div className="mt-1 text-xs text-gray-500">
                CESI {toast.payload.score.toFixed(1)} — {toast.payload.severity.replace("_", " ")}
              </div>
            </div>
            <button
              onClick={() => dismiss(toast.id)}
              className="text-gray-500 hover:text-gray-300 text-sm leading-none ml-2"
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
