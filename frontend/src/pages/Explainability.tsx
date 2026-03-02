import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api, type SHAPExplanation } from "../api/client";

/* ── Waterfall bar (single feature) ──────────────────────────────── */
function WaterfallBar({
  feature,
  shapValue,
  rawValue,
  maxAbs,
}: {
  feature: string;
  shapValue: number;
  rawValue: number;
  maxAbs: number;
}) {
  const pct = maxAbs > 0 ? Math.abs(shapValue) / maxAbs : 0;
  const isPositive = shapValue > 0;

  return (
    <div className="flex items-center gap-3 py-1.5">
      <div className="w-40 text-right text-xs text-gray-400 truncate" title={feature}>
        {feature}
      </div>
      <div className="flex-1 flex items-center">
        {/* Negative side */}
        <div className="flex-1 flex justify-end">
          {!isPositive && (
            <div
              className="h-5 rounded-l bg-gradient-to-r from-blue-600 to-blue-400 relative"
              style={{ width: `${pct * 100}%` }}
            >
              <span className="absolute right-1 top-0 text-[10px] text-white leading-5">
                {shapValue.toFixed(3)}
              </span>
            </div>
          )}
        </div>
        {/* Center line */}
        <div className="w-px h-7 bg-gray-600" />
        {/* Positive side */}
        <div className="flex-1">
          {isPositive && (
            <div
              className="h-5 rounded-r bg-gradient-to-r from-red-400 to-red-600 relative"
              style={{ width: `${pct * 100}%` }}
            >
              <span className="absolute left-1 top-0 text-[10px] text-white leading-5">
                +{shapValue.toFixed(3)}
              </span>
            </div>
          )}
        </div>
      </div>
      <div className="w-16 text-right text-xs font-mono text-gray-500">
        {rawValue.toFixed(2)}
      </div>
    </div>
  );
}

/* ── SHAP panel for one region ────────────────────────────────────── */
function SHAPPanel({ regionCode }: { regionCode: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["explain", regionCode],
    queryFn: () => api.explain(regionCode),
    staleTime: 120_000,
  });

  if (isLoading)
    return (
      <div className="glass-panel p-6 text-center text-gray-500">
        Computing SHAP values for <span className="font-mono text-blue-300">{regionCode}</span>…
      </div>
    );

  if (isError)
    return (
      <div className="glass-panel p-6 text-center text-red-400">
        {(error as Error).message}
      </div>
    );

  if (!data || data.features.length === 0)
    return (
      <div className="glass-panel p-6 text-center text-gray-500">
        No SHAP data available for this region.
      </div>
    );

  const sorted = [...data.features].sort(
    (a, b) => Math.abs(b.shap_value) - Math.abs(a.shap_value),
  );
  const maxAbs = Math.max(...sorted.map((f) => Math.abs(f.shap_value)));

  return (
    <div className="glass-panel p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-300">
            SHAP Feature Attribution —{" "}
            <span className="font-mono text-blue-300">{regionCode}</span>
          </h3>
          {data.cesi_score !== null && (
            <p className="text-xs text-gray-500 mt-0.5">
              Current CESI: {data.cesi_score.toFixed(1)}
            </p>
          )}
        </div>
        <span className="text-xs text-gray-600">
          {new Date(data.generated_at).toLocaleString()}
        </span>
      </div>

      {/* Legend */}
      <div className="flex gap-4 text-xs text-gray-500 mb-2">
        <span className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-red-500" /> Risk ↑
        </span>
        <span className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-blue-500" /> Risk ↓
        </span>
        <span className="ml-auto">Raw Value →</span>
      </div>

      {/* Waterfall chart */}
      <div className="space-y-0">
        {sorted.map((f) => (
          <WaterfallBar
            key={f.feature}
            feature={f.feature}
            shapValue={f.shap_value}
            rawValue={f.raw_value}
            maxAbs={maxAbs}
          />
        ))}
      </div>
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────────────── */
export default function ExplainabilityPage() {
  const { regionCode: paramRegion } = useParams<{ regionCode: string }>();
  const [regionInput, setRegionInput] = useState(paramRegion ?? "EU");
  const [activeRegion, setActiveRegion] = useState(paramRegion ?? "EU");

  const regions = useQuery({
    queryKey: ["regions"],
    queryFn: api.listRegions,
  });

  return (
    <div className="h-full overflow-auto p-6 space-y-4">
      <div>
        <h2 className="text-xl font-semibold">Explainability</h2>
        <p className="text-sm text-gray-400 mt-0.5">
          SHAP-based feature attribution — understand what drives each CESI
          score
        </p>
      </div>

      {/* Region selector */}
      <div className="flex gap-2 items-end">
        <label className="space-y-1 text-sm">
          <span className="text-gray-400">Region</span>
          <select
            className="input-field"
            value={regionInput}
            onChange={(e) => setRegionInput(e.target.value)}
          >
            {regions.data?.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name} ({r.code})
              </option>
            ))}
          </select>
        </label>
        <button
          onClick={() => setActiveRegion(regionInput)}
          className="btn-primary"
        >
          Explain
        </button>
      </div>

      <SHAPPanel regionCode={activeRegion} />
    </div>
  );
}
