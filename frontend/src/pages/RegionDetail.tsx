import { useState, useCallback, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { severityClass, formatCESI, formatProbability } from "../lib/utils";
import CESITrendChart from "../components/CESITrendChart";
import CrisisBreakdown from "../components/CrisisBreakdown";
import CorrelationMatrix from "../components/CorrelationMatrix";
import PlaybackSlider from "../components/PlaybackSlider";
import { useCesiScoresWS, type CesiUpdatePayload } from "../hooks/useWebSocket";

export default function RegionDetail() {
  const { regionCode } = useParams<{ regionCode: string }>();
  const queryClient = useQueryClient();

  // ── Data fetching ──────────────────────────────────────────────────
  const { data, isLoading } = useQuery({
    queryKey: ["cesi-detail", regionCode],
    queryFn: () => api.regionDetail(regionCode!),
    enabled: !!regionCode,
  });

  const { data: history } = useQuery({
    queryKey: ["cesi-history", regionCode],
    queryFn: () => api.cesiHistory(regionCode!, 180),
    enabled: !!regionCode,
  });

  // ── WebSocket live updates ─────────────────────────────────────────
  const handleWSUpdate = useCallback(
    (payload: CesiUpdatePayload) => {
      if (payload.region_code === regionCode?.toUpperCase()) {
        // Invalidate queries to pick up the new score
        queryClient.invalidateQueries({ queryKey: ["cesi-detail", regionCode] });
        queryClient.invalidateQueries({ queryKey: ["cesi-history", regionCode] });
      }
    },
    [regionCode, queryClient],
  );
  const { status: wsStatus } = useCesiScoresWS(handleWSUpdate);

  // ── Playback state ─────────────────────────────────────────────────
  const historyList = history ?? data?.history ?? [];
  const [playbackIndex, setPlaybackIndex] = useState(
    () => Math.max(0, historyList.length - 1),
  );

  // Keep playback at latest when new data comes in
  const effectiveIndex = Math.min(playbackIndex, Math.max(0, historyList.length - 1));

  // Build layer history arrays for correlation matrix (from available CESI scores)
  const layerHistory = useMemo(() => {
    // We don't have per-layer time series from the simple history endpoint,
    // so we pass undefined and let CorrelationMatrix fall back to single-point mode
    return undefined;
  }, []);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-gray-400">
        Loading region data…
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-full items-center justify-center text-gray-400">
        Region not found
      </div>
    );
  }

  const { region, current_score: score, predictions } = data;

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/"
            className="rounded-lg bg-slate-800 px-2 py-1 text-sm text-gray-400 hover:text-white transition"
          >
            ← Globe
          </Link>
          <div>
            <h2 className="text-2xl font-bold">{region.name}</h2>
            <p className="text-sm text-gray-400">{region.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {/* WS status indicator */}
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <div
              className={`h-1.5 w-1.5 rounded-full ${
                wsStatus === "connected"
                  ? "bg-green-500 animate-pulse"
                  : wsStatus === "connecting"
                    ? "bg-yellow-500 animate-pulse"
                    : "bg-gray-600"
              }`}
            />
            {wsStatus === "connected" ? "Live" : wsStatus}
          </div>
          {score && (
            <div className="text-right">
              <div className="text-4xl font-bold">{formatCESI(score.score)}</div>
              <span className={`severity-badge ${severityClass(score.severity)}`}>
                {score.severity.replace("_", " ").toUpperCase()}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ── CESI Trend Chart ─────────────────────────────────────────── */}
      {historyList.length >= 2 && (
        <div className="glass-panel p-4">
          <h3 className="mb-3 text-sm font-semibold uppercase text-gray-400">
            CESI Trend
          </h3>
          <CESITrendChart history={historyList} width={640} height={200} />

          {/* Playback slider */}
          <div className="mt-3">
            <PlaybackSlider
              history={historyList}
              currentIndex={effectiveIndex}
              onIndexChange={setPlaybackIndex}
              width={640}
            />
          </div>
        </div>
      )}

      {/* ── Layer breakdown ──────────────────────────────────────────── */}
      {score && (
        <div className="glass-panel p-4">
          <h3 className="mb-3 text-sm font-semibold uppercase text-gray-400">
            Signal Layer Breakdown
          </h3>
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(score.layer_scores).map(([layer, data]) => (
              <div key={layer} className="rounded-lg bg-slate-800/50 p-3">
                <div className="text-xs text-gray-400">
                  {layer.replace("_", " ")}
                </div>
                <div className="mt-1 text-lg font-semibold">
                  {(data as any).raw_anomaly?.toFixed(1) ?? "—"}
                </div>
                <div className="text-xs text-gray-500">
                  weight: {((data as any).weight * 100).toFixed(0)}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Two-column: Crisis radar + Correlation matrix */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── Crisis Breakdown Radar ───────────────────────────────────── */}
        {score && Object.keys(score.crisis_probabilities).length > 0 && (
          <div className="glass-panel p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase text-gray-400">
              Crisis Probability Radar
            </h3>
            <CrisisBreakdown probabilities={score.crisis_probabilities} size={280} />
          </div>
        )}

        {/* ── Signal Correlation Matrix ────────────────────────────────── */}
        {score && Object.keys(score.layer_scores).length > 0 && (
          <div className="glass-panel p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase text-gray-400">
              Signal Correlation Matrix
            </h3>
            <CorrelationMatrix
              layerScores={score.layer_scores}
              layerHistory={layerHistory}
              size={320}
            />
          </div>
        )}
      </div>

      {/* ── Crisis probabilities list ──────────────────────────────── */}
      {predictions.length > 0 && (
        <div className="glass-panel p-4">
          <h3 className="mb-3 text-sm font-semibold uppercase text-gray-400">
            Crisis Probabilities (12-month horizon)
          </h3>
          <div className="space-y-2">
            {predictions.map((pred) => (
              <div
                key={pred.id}
                className="flex items-center justify-between rounded-lg bg-slate-800/50 px-3 py-2"
              >
                <span className="text-sm">
                  {pred.crisis_type.replace("_", " ")}
                </span>
                <div className="flex items-center gap-2">
                  <div className="h-2 w-24 rounded-full bg-slate-700">
                    <div
                      className="h-2 rounded-full bg-red-500"
                      style={{ width: `${pred.probability * 100}%` }}
                    />
                  </div>
                  <span className="w-14 text-right text-sm font-mono">
                    {formatProbability(pred.probability)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Amplification notice */}
      {score?.amplification_applied && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300">
          Cross-layer amplification active — multiple signal layers are spiking
          simultaneously, indicating correlated structural stress.
        </div>
      )}
    </div>
  );
}
