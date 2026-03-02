import type { CESIScore, RegionSummary } from "../api/client";
import { severityClass, formatCESI } from "../lib/utils";

interface Props {
  scores: CESIScore[];
  regions: RegionSummary[];
}

export default function CESIPanel({ scores, regions }: Props) {
  const regionMap = new Map(regions.map((r) => [r.id, r]));

  if (scores.length === 0) {
    return (
      <div className="glass-panel p-4 text-center text-sm text-gray-500">
        No CESI scores available yet
      </div>
    );
  }

  // Sort by score descending (highest risk first)
  const sorted = [...scores].sort((a, b) => b.score - a.score);

  return (
    <div className="glass-panel p-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
        Global Risk Overview
      </h3>
      <div className="space-y-2">
        {sorted.map((s) => {
          const region = regionMap.get(s.region_id);
          return (
            <div
              key={s.id}
              className="flex items-center justify-between rounded-lg bg-slate-800/50 px-3 py-2"
            >
              <div>
                <div className="text-sm font-medium">
                  {region?.name ?? "Unknown"}
                </div>
                <div className="text-xs text-gray-500">
                  {new Date(s.scored_at).toLocaleDateString()}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold font-mono">
                  {formatCESI(s.score)}
                </span>
                <span className={`severity-badge ${severityClass(s.severity)}`}>
                  {s.severity.replace("_", " ")}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      {scores.some((s) => s.amplification_applied) && (
        <div className="mt-3 text-xs text-amber-400/80">
          ⚠ Cross-layer amplification active for one or more regions
        </div>
      )}
    </div>
  );
}
