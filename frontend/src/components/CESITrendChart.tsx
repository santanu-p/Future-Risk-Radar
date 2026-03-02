/** CESI Trend Line Chart — renders a historical CESI score sparkline with severity colour bands.
 *
 * Uses D3 for scales + path generation with React rendering.
 */

import { useMemo } from "react";
import * as d3 from "d3";
import type { CESIHistoryPoint } from "../api/client";
import { severityColor } from "../lib/utils";

interface Props {
  history: CESIHistoryPoint[];
  width?: number;
  height?: number;
  showAxes?: boolean;
}

// Severity band thresholds matching backend SeverityLevel
const SEVERITY_BANDS = [
  { max: 20, label: "stable", color: "rgba(34, 197, 94, 0.08)" },
  { max: 40, label: "elevated", color: "rgba(234, 179, 8, 0.08)" },
  { max: 60, label: "concerning", color: "rgba(249, 115, 22, 0.08)" },
  { max: 80, label: "high_risk", color: "rgba(239, 68, 68, 0.08)" },
  { max: 100, label: "critical", color: "rgba(220, 38, 38, 0.12)" },
];

export default function CESITrendChart({
  history,
  width = 560,
  height = 200,
  showAxes = true,
}: Props) {
  const margin = { top: 12, right: 16, bottom: showAxes ? 28 : 4, left: showAxes ? 40 : 4 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  const parsed = useMemo(
    () =>
      history
        .map((h) => ({ ...h, date: new Date(h.scored_at) }))
        .sort((a, b) => a.date.getTime() - b.date.getTime()),
    [history],
  );

  const xScale = useMemo(
    () =>
      d3
        .scaleTime()
        .domain(d3.extent(parsed, (d) => d.date) as [Date, Date])
        .range([0, innerW]),
    [parsed, innerW],
  );

  const yScale = useMemo(
    () => d3.scaleLinear().domain([0, 100]).range([innerH, 0]),
    [innerH],
  );

  const line = useMemo(
    () =>
      d3
        .line<(typeof parsed)[0]>()
        .x((d) => xScale(d.date))
        .y((d) => yScale(d.score))
        .curve(d3.curveMonotoneX),
    [xScale, yScale],
  );

  const area = useMemo(
    () =>
      d3
        .area<(typeof parsed)[0]>()
        .x((d) => xScale(d.date))
        .y0(innerH)
        .y1((d) => yScale(d.score))
        .curve(d3.curveMonotoneX),
    [xScale, yScale, innerH],
  );

  if (parsed.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-sm text-gray-500"
        style={{ width, height }}
      >
        Not enough data for trend chart
      </div>
    );
  }

  const latestPoint = parsed[parsed.length - 1];
  if (!latestPoint) {
    return (
      <div
        className="flex items-center justify-center text-sm text-gray-500"
        style={{ width, height }}
      >
        Not enough data for trend chart
      </div>
    );
  }

  const latestSeverity = latestPoint.severity;
  const [r, g, b] = severityColor(latestSeverity);

  const xTicks = xScale.ticks(5);
  const yTicks = yScale.ticks(5);

  return (
    <svg width={width} height={height} className="overflow-visible">
      <g transform={`translate(${margin.left},${margin.top})`}>
        {/* Severity bands */}
        {SEVERITY_BANDS.map((band, i) => {
          const prevMax = i > 0 ? SEVERITY_BANDS[i - 1].max : 0;
          const y1 = yScale(band.max);
          const y2 = yScale(prevMax);
          return (
            <rect
              key={band.label}
              x={0}
              y={y1}
              width={innerW}
              height={y2 - y1}
              fill={band.color}
            />
          );
        })}

        {/* Grid lines */}
        {yTicks.map((t) => (
          <line
            key={t}
            x1={0}
            x2={innerW}
            y1={yScale(t)}
            y2={yScale(t)}
            stroke="rgba(148,163,184,0.1)"
          />
        ))}

        {/* Area fill */}
        <path d={area(parsed) ?? ""} fill={`rgba(${r},${g},${b},0.12)`} />

        {/* Line */}
        <path
          d={line(parsed) ?? ""}
          fill="none"
          stroke={`rgb(${r},${g},${b})`}
          strokeWidth={2}
          strokeLinejoin="round"
        />

        {/* Data point dots (only if < 60 points) */}
        {parsed.length <= 60 &&
          parsed.map((d, i) => {
            const [dr, dg, db] = severityColor(d.severity);
            return (
              <circle
                key={i}
                cx={xScale(d.date)}
                cy={yScale(d.score)}
                r={2.5}
                fill={`rgb(${dr},${dg},${db})`}
                stroke="rgba(15,23,42,0.8)"
                strokeWidth={1}
              />
            );
          })}

        {/* Latest value label */}
        <text
          x={innerW + 6}
          y={yScale(latestPoint.score)}
          fill={`rgb(${r},${g},${b})`}
          fontSize={12}
          fontWeight={700}
          dominantBaseline="middle"
        >
          {latestPoint.score.toFixed(1)}
        </text>

        {/* Axes */}
        {showAxes && (
          <>
            {/* Y axis */}
            {yTicks.map((t) => (
              <text
                key={t}
                x={-8}
                y={yScale(t)}
                fill="#94a3b8"
                fontSize={10}
                textAnchor="end"
                dominantBaseline="middle"
              >
                {t}
              </text>
            ))}
            {/* X axis */}
            {xTicks.map((t) => (
              <text
                key={t.getTime()}
                x={xScale(t)}
                y={innerH + 18}
                fill="#94a3b8"
                fontSize={10}
                textAnchor="middle"
              >
                {d3.timeFormat("%b %d")(t)}
              </text>
            ))}
          </>
        )}
      </g>
    </svg>
  );
}
