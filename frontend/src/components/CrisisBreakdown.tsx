/** Crisis Type Breakdown — radar + bar chart showing per-crisis-type probabilities.
 *
 * Renders a D3-based radar polygon overlaid on a labelled axes grid.
 */

import { useMemo } from "react";
import * as d3 from "d3";
import type { CrisisProbability } from "../api/client";

interface Props {
  probabilities: Record<string, CrisisProbability>;
  size?: number;
}

const CRISIS_LABELS: Record<string, string> = {
  recession: "Recession",
  sovereign_default: "Sovereign Default",
  banking_crisis: "Banking Crisis",
  currency_crisis: "Currency Crisis",
  political_unrest: "Political Unrest",
  supply_shock: "Supply Shock",
  tech_disruption: "Tech Disruption",
  energy_crisis: "Energy Crisis",
};

const AXIS_COLORS = [
  "#ef4444", "#f97316", "#eab308", "#22c55e",
  "#3b82f6", "#8b5cf6", "#ec4899", "#06b6d4",
];

export default function CrisisBreakdown({ probabilities, size = 280 }: Props) {
  const entries = useMemo(
    () =>
      Object.entries(probabilities).map(([key, val]) => ({
        key,
        label: CRISIS_LABELS[key] ?? key.replace(/_/g, " "),
        ...val,
      })),
    [probabilities],
  );

  if (entries.length === 0) {
    return (
      <div className="text-center text-sm text-gray-500 py-4">
        No crisis probability data
      </div>
    );
  }

  const n = entries.length;
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 - 40;
  const angleSlice = (2 * Math.PI) / n;

  const rScale = d3.scaleLinear().domain([0, 1]).range([0, R]);

  // Radar polygon points
  const radarPoints = entries.map((e, i) => {
    const angle = angleSlice * i - Math.PI / 2;
    return {
      x: cx + rScale(e.probability) * Math.cos(angle),
      y: cy + rScale(e.probability) * Math.sin(angle),
    };
  });

  const radarPath =
    radarPoints.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ") +
    " Z";

  // Confidence interval polygon
  const ciOuterPoints = entries.map((e, i) => {
    const angle = angleSlice * i - Math.PI / 2;
    return {
      x: cx + rScale(e.ci_upper) * Math.cos(angle),
      y: cy + rScale(e.ci_upper) * Math.sin(angle),
    };
  });
  const ciInnerPoints = entries.map((e, i) => {
    const angle = angleSlice * i - Math.PI / 2;
    return {
      x: cx + rScale(e.ci_lower) * Math.cos(angle),
      y: cy + rScale(e.ci_lower) * Math.sin(angle),
    };
  });

  const ciPath =
    ciOuterPoints.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ") +
    " " +
    ciInnerPoints
      .slice()
      .reverse()
      .map((p, i) => `${i === 0 ? "L" : "L"} ${p.x} ${p.y}`)
      .join(" ") +
    " Z";

  const gridLevels = [0.2, 0.4, 0.6, 0.8, 1.0];

  return (
    <div className="flex flex-col items-center gap-4">
      <svg width={size} height={size} className="overflow-visible">
        {/* Grid circles */}
        {gridLevels.map((level) => (
          <circle
            key={level}
            cx={cx}
            cy={cy}
            r={rScale(level)}
            fill="none"
            stroke="rgba(148,163,184,0.12)"
          />
        ))}

        {/* Grid level labels */}
        {gridLevels.map((level) => (
          <text
            key={`lbl-${level}`}
            x={cx + 4}
            y={cy - rScale(level) + 1}
            fill="#64748b"
            fontSize={9}
          >
            {(level * 100).toFixed(0)}%
          </text>
        ))}

        {/* Axes */}
        {entries.map((_, i) => {
          const angle = angleSlice * i - Math.PI / 2;
          return (
            <line
              key={i}
              x1={cx}
              y1={cy}
              x2={cx + R * Math.cos(angle)}
              y2={cy + R * Math.sin(angle)}
              stroke="rgba(148,163,184,0.15)"
            />
          );
        })}

        {/* CI band */}
        <path d={ciPath} fill="rgba(239, 68, 68, 0.08)" />

        {/* Radar polygon */}
        <path
          d={radarPath}
          fill="rgba(239, 68, 68, 0.2)"
          stroke="#ef4444"
          strokeWidth={2}
        />

        {/* Data dots */}
        {radarPoints.map((p, i) => (
          <circle
            key={i}
            cx={p.x}
            cy={p.y}
            r={4}
            fill={AXIS_COLORS[i % AXIS_COLORS.length]}
            stroke="rgba(15,23,42,0.8)"
            strokeWidth={1.5}
          />
        ))}

        {/* Axis labels */}
        {entries.map((e, i) => {
          const angle = angleSlice * i - Math.PI / 2;
          const labelR = R + 22;
          const lx = cx + labelR * Math.cos(angle);
          const ly = cy + labelR * Math.sin(angle);
          return (
            <text
              key={i}
              x={lx}
              y={ly}
              fill="#cbd5e1"
              fontSize={10}
              fontWeight={600}
              textAnchor="middle"
              dominantBaseline="middle"
            >
              {e.label}
            </text>
          );
        })}
      </svg>

      {/* Legend bar list */}
      <div className="w-full space-y-1.5">
        {entries
          .sort((a, b) => b.probability - a.probability)
          .map((e, i) => (
            <div key={e.key} className="flex items-center gap-2">
              <div
                className="h-2 w-2 rounded-full flex-shrink-0"
                style={{ backgroundColor: AXIS_COLORS[i % AXIS_COLORS.length] }}
              />
              <span className="text-xs text-gray-400 w-28 truncate">{e.label}</span>
              <div className="flex-1 h-1.5 rounded-full bg-slate-800">
                <div
                  className="h-1.5 rounded-full bg-red-500 transition-all"
                  style={{ width: `${e.probability * 100}%` }}
                />
              </div>
              <span className="text-xs font-mono text-gray-300 w-12 text-right">
                {(e.probability * 100).toFixed(1)}%
              </span>
            </div>
          ))}
      </div>
    </div>
  );
}
