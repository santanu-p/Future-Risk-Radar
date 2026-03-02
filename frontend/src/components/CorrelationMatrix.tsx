/** Signal Correlation Matrix — heatmap of pairwise signal layer correlations.
 *
 * Renders an SVG heatmap with hover tooltips, matching the dark UI theme.
 */

import { useMemo, useState } from "react";
import * as d3 from "d3";
import type { LayerScore } from "../api/client";

interface Props {
  /** Map of layer name → LayerScore (contribution values used for correlation) */
  layerScores: Record<string, LayerScore>;
  /** History of layer scores over time (needed for actual correlation) */
  layerHistory?: Record<string, number[]>;
  size?: number;
}

const LAYER_LABELS: Record<string, string> = {
  research_funding: "Research",
  patent_activity: "Patents",
  supply_chain: "Supply",
  energy_conflict: "Energy",
  macro_financial: "Macro",
};

/** Fallback: compute mock correlation from single-point layer scores using cosine similarity proxy. */
function computeCorrelationMatrix(
  layerHistory: Record<string, number[]>,
): { labels: string[]; matrix: number[][] } {
  const labels = Object.keys(layerHistory).sort();
  const n = labels.length;
  const matrix: number[][] = Array.from({ length: n }, () => Array(n).fill(0));

  for (let i = 0; i < n; i++) {
    const row = matrix[i];
    const labelI = labels[i];
    if (!row || !labelI) continue;

    for (let j = 0; j < n; j++) {
      const labelJ = labels[j];
      if (!labelJ) continue;

      if (i === j) {
        row[j] = 1;
        continue;
      }
      const a = layerHistory[labelI];
      const b = layerHistory[labelJ];
      if (!a || !b) {
        row[j] = 0;
        continue;
      }
      const len = Math.min(a.length, b.length);
      if (len < 3) {
        row[j] = 0;
        continue;
      }
      // Pearson correlation
      const meanA = a.slice(0, len).reduce((s: number, v: number) => s + v, 0) / len;
      const meanB = b.slice(0, len).reduce((s: number, v: number) => s + v, 0) / len;
      let num = 0, denA = 0, denB = 0;
      for (let k = 0; k < len; k++) {
        const av = a[k];
        const bv = b[k];
        if (av === undefined || bv === undefined) continue;
        const da = av - meanA;
        const db = bv - meanB;
        num += da * db;
        denA += da * da;
        denB += db * db;
      }
      const den = Math.sqrt(denA) * Math.sqrt(denB);
      row[j] = den === 0 ? 0 : num / den;
    }
  }

  return { labels, matrix };
}

/** Simple heatmap from single-point contributions when no history available. */
function matrixFromSinglePoint(layerScores: Record<string, LayerScore>): {
  labels: string[];
  matrix: number[][];
} {
  const labels = Object.keys(layerScores).sort();
  const n = labels.length;
  const vals = labels.map((l) => layerScores[l]?.contribution ?? 0);
  const matrix: number[][] = Array.from({ length: n }, () => Array(n).fill(0));

  for (let i = 0; i < n; i++) {
    const row = matrix[i];
    const vi = vals[i] ?? 0;
    if (!row) continue;

    for (let j = 0; j < n; j++) {
      if (i === j) {
        row[j] = 1;
      } else {
        // Normalised product as rough proxy
        const maxV = Math.max(...vals.map(Math.abs), 1);
        const vj = vals[j] ?? 0;
        row[j] = (vi * vj) / (maxV * maxV);
      }
    }
  }
  return { labels, matrix };
}

export default function CorrelationMatrix({
  layerScores,
  layerHistory,
  size = 320,
}: Props) {
  const [hovered, setHovered] = useState<{ i: number; j: number } | null>(null);

  const { labels, matrix } = useMemo(() => {
    if (layerHistory && Object.keys(layerHistory).length > 0) {
      return computeCorrelationMatrix(layerHistory);
    }
    return matrixFromSinglePoint(layerScores);
  }, [layerScores, layerHistory]);

  const n = labels.length;
  if (n === 0) return null;

  const margin = 64;
  const cellSize = (size - margin) / n;

  const colorScale = d3
    .scaleSequential(d3.interpolateRdBu)
    .domain([1, -1]); // Reversed so red = positive correlation

  const hoveredI = hovered?.i;
  const hoveredJ = hovered?.j;
  const hoveredRow = hoveredI !== undefined ? matrix[hoveredI] : undefined;
  const hoveredValue = hoveredRow && hoveredJ !== undefined ? hoveredRow[hoveredJ] : undefined;
  const hoveredLabelI = hoveredI !== undefined ? labels[hoveredI] : undefined;
  const hoveredLabelJ = hoveredJ !== undefined ? labels[hoveredJ] : undefined;

  return (
    <div className="relative">
      <svg width={size} height={size} className="overflow-visible">
        <g transform={`translate(${margin}, ${margin})`}>
          {/* Cells */}
          {matrix.map((row, i) =>
            row.map((val, j) => (
              <rect
                key={`${i}-${j}`}
                x={j * cellSize}
                y={i * cellSize}
                width={cellSize - 1}
                height={cellSize - 1}
                rx={3}
                fill={colorScale(val)}
                opacity={hovered && (hovered.i !== i || hovered.j !== j) ? 0.4 : 0.9}
                onMouseEnter={() => setHovered({ i, j })}
                onMouseLeave={() => setHovered(null)}
                className="transition-opacity cursor-pointer"
              />
            )),
          )}

          {/* Cell value text */}
          {matrix.map((row, i) =>
            row.map((val, j) => (
              <text
                key={`t-${i}-${j}`}
                x={j * cellSize + cellSize / 2}
                y={i * cellSize + cellSize / 2}
                fill={Math.abs(val) > 0.4 ? "#fff" : "#94a3b8"}
                fontSize={10}
                fontWeight={600}
                textAnchor="middle"
                dominantBaseline="middle"
                pointerEvents="none"
              >
                {val.toFixed(2)}
              </text>
            )),
          )}

          {/* Column labels (top) */}
          {labels.map((label, i) => (
            <text
              key={`col-${i}`}
              x={i * cellSize + cellSize / 2}
              y={-6}
              fill="#cbd5e1"
              fontSize={10}
              textAnchor="middle"
              fontWeight={500}
            >
              {LAYER_LABELS[label] ?? label}
            </text>
          ))}

          {/* Row labels (left) */}
          {labels.map((label, i) => (
            <text
              key={`row-${i}`}
              x={-6}
              y={i * cellSize + cellSize / 2}
              fill="#cbd5e1"
              fontSize={10}
              textAnchor="end"
              dominantBaseline="middle"
              fontWeight={500}
            >
              {LAYER_LABELS[label] ?? label}
            </text>
          ))}
        </g>
      </svg>

      {/* Tooltip */}
      {hovered && hoveredLabelI && hoveredLabelJ && hoveredValue !== undefined && (
        <div className="absolute top-0 right-0 glass-panel px-2 py-1 text-xs">
          <span className="text-gray-400">
            {LAYER_LABELS[hoveredLabelI] ?? hoveredLabelI}
          </span>
          {" × "}
          <span className="text-gray-400">
            {LAYER_LABELS[hoveredLabelJ] ?? hoveredLabelJ}
          </span>
          <span className="ml-2 font-mono font-bold text-white">
            {hoveredValue.toFixed(3)}
          </span>
        </div>
      )}
    </div>
  );
}
