/** API client configuration and typed fetch helpers. */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

// ── Types ─────────────────────────────────────────────────────────────

export interface RegionSummary {
  id: string;
  code: string;
  name: string;
  centroid_lat: number;
  centroid_lon: number;
  latest_cesi: number | null;
  severity: string | null;
}

export interface Region {
  id: string;
  code: string;
  name: string;
  description: string | null;
  iso_codes: Record<string, string[]>;
  centroid_lat: number;
  centroid_lon: number;
  active: boolean;
  created_at: string;
}

export interface CESIScore {
  id: string;
  region_id: string;
  score: number;
  severity: string;
  layer_scores: Record<string, LayerScore>;
  crisis_probabilities: Record<string, CrisisProbability>;
  amplification_applied: boolean;
  model_version: string;
  scored_at: string;
}

export interface LayerScore {
  raw_anomaly: number;
  weight: number;
  contribution: number;
}

export interface CrisisProbability {
  probability: number;
  ci_lower: number;
  ci_upper: number;
}

export interface CESIHistoryPoint {
  score: number;
  severity: string;
  scored_at: string;
}

export interface CESIRegionDetail {
  region: Region;
  current_score: CESIScore | null;
  history: CESIHistoryPoint[];
  predictions: Prediction[];
}

export interface Prediction {
  id: string;
  region_id: string;
  crisis_type: string;
  probability: number;
  confidence_lower: number;
  confidence_upper: number;
  horizon_date: string;
  model_version: string;
  explanation: Record<string, unknown>;
  created_at: string;
}

export interface SignalTimeSeriesPoint {
  ts: string;
  value: number;
  zscore: number | null;
  is_anomaly: boolean;
}

export interface SignalTimeSeries {
  region_code: string;
  source: string;
  indicator: string;
  layer: string;
  data: SignalTimeSeriesPoint[];
}

export interface TrainingStatus {
  status: "idle" | "running" | "completed" | "failed";
  started_at: string | null;
  completed_at: string | null;
  current_step: string | null;
  progress: number;
  error: string | null;
}

export interface BacktestResult {
  total_points: number;
  detections: number;
  avg_brier_score: number;
  avg_brier_skill_score: number;
  avg_auc: number;
  brier_scores: Record<string, number>;
  roc_results: Record<string, { auc: number; best_threshold: number }>;
  known_crisis_validations: Array<{
    name: string;
    region: string;
    detected: boolean;
    peak_score: number;
  }>;
}

// ── Fetch helpers ─────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem("frr_token");
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...init?.headers,
  };

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ── Endpoints ─────────────────────────────────────────────────────────

export const api = {
  // Regions
  listRegions: () => apiFetch<RegionSummary[]>("/regions/"),
  getRegion: (code: string) => apiFetch<Region>(`/regions/${code}`),

  // CESI
  latestScores: () => apiFetch<CESIScore[]>("/cesi/scores"),
  regionDetail: (code: string) => apiFetch<CESIRegionDetail>(`/cesi/${code}`),
  cesiHistory: (code: string, limit = 90) =>
    apiFetch<CESIHistoryPoint[]>(`/cesi/${code}/history?limit=${limit}`),

  // Signals
  signalTimeSeries: (code: string, source: string, indicator: string) =>
    apiFetch<SignalTimeSeries>(
      `/signals/${code}/timeseries?source=${source}&indicator=${indicator}`,
    ),

  // Auth
  login: (email: string, password: string) =>
    apiFetch<{ access_token: string; expires_in: number }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  // Training & backtest
  triggerTraining: () =>
    apiFetch<{ status: string; message: string }>("/train", {
      method: "POST",
    }),
  trainingStatus: () =>
    apiFetch<TrainingStatus>("/train/status"),
  runBacktest: (startDate?: string, endDate?: string) => {
    const params = new URLSearchParams();
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    const qs = params.toString();
    return apiFetch<BacktestResult>(`/backtest${qs ? `?${qs}` : ""}`);
  },
} as const;
