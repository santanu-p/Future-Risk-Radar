/** WebSocket hook — connects to FRR backend for live score / signal push.
 *
 * Reconnects automatically with exponential backoff.
 */

import { useEffect, useRef, useCallback, useState } from "react";

export interface WSMessage<T = unknown> {
  channel: string;
  data: T;
}

export interface CesiUpdatePayload {
  event: "cesi_update";
  region_code: string;
  score: number;
  severity: string;
  amplification_applied: boolean;
  scored_at: string;
  crisis_probabilities: Record<string, { probability: number; ci_lower: number; ci_upper: number }>;
}

export interface AlertPayload {
  event: "threshold_breach";
  region_code: string;
  score: number;
  severity: string;
  message: string;
}

export interface SignalPayload {
  event: "signal_ingested";
  source: string;
  indicator: string;
  value: number;
  ts: string;
  layer: string;
}

type ConnectionStatus = "connecting" | "connected" | "disconnected";

interface UseWebSocketOptions {
  /** Relative WebSocket path, e.g. "/ws/scores" */
  path: string;
  /** Callback invoked for every incoming message */
  onMessage?: (msg: WSMessage) => void;
  /** Whether to auto-connect on mount (default: true) */
  enabled?: boolean;
}

const WS_BASE = import.meta.env.VITE_WS_BASE_URL ||
  `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;

const MAX_BACKOFF_MS = 30_000;

export function useWebSocket({ path, onMessage, enabled = true }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(1_000);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");

  const connect = useCallback(() => {
    if (!enabled) return;

    const url = `${WS_BASE}${path}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;
    setStatus("connecting");

    ws.onopen = () => {
      setStatus("connected");
      backoffRef.current = 1_000;
    };

    ws.onmessage = (evt) => {
      try {
        const msg: WSMessage = JSON.parse(evt.data);
        onMessage?.(msg);
      } catch {
        // ignore non-JSON messages (pong, etc.)
      }
    };

    ws.onclose = () => {
      setStatus("disconnected");
      // Reconnect with exponential backoff
      reconnectTimer.current = setTimeout(() => {
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS);
        connect();
      }, backoffRef.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [path, onMessage, enabled]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current !== null) {
        clearTimeout(reconnectTimer.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  // Heartbeat ping every 25 s to keep the connection alive
  useEffect(() => {
    if (status !== "connected") return;
    const interval = setInterval(() => {
      wsRef.current?.send("ping");
    }, 25_000);
    return () => clearInterval(interval);
  }, [status]);

  return { status };
}

// ── Convenience hooks ────────────────────────────────────────────────

/**
 * Subscribe to live CESI scores for all regions.
 * Returns the latest update (or null) and connection status.
 */
export function useCesiScoresWS(onUpdate?: (payload: CesiUpdatePayload) => void) {
  const [latest, setLatest] = useState<CesiUpdatePayload | null>(null);

  const handleMessage = useCallback(
    (msg: WSMessage) => {
      const data = msg.data as CesiUpdatePayload;
      if (data.event === "cesi_update") {
        setLatest(data);
        onUpdate?.(data);
      }
    },
    [onUpdate],
  );

  const { status } = useWebSocket({
    path: "/ws/scores",
    onMessage: handleMessage,
  });

  return { latest, status };
}

/**
 * Subscribe to alert events.
 */
export function useAlertsWS(onAlert?: (payload: AlertPayload) => void) {
  const [alerts, setAlerts] = useState<AlertPayload[]>([]);

  const handleMessage = useCallback(
    (msg: WSMessage) => {
      const data = msg.data as AlertPayload;
      if (data.event === "threshold_breach") {
        setAlerts((prev) => [data, ...prev].slice(0, 50));
        onAlert?.(data);
      }
    },
    [onAlert],
  );

  const { status } = useWebSocket({
    path: "/ws/alerts",
    onMessage: handleMessage,
  });

  return { alerts, status };
}
