/** Historical Playback Slider — scrub through CESI history with temporal context.
 *
 * Renders a range slider with a mini sparkline background and date labels.
 * When the user drags the slider, the parent receives the selected date index.
 */

import { useMemo, useCallback } from "react";
import * as d3 from "d3";
import type { CESIHistoryPoint } from "../api/client";

interface Props {
  history: CESIHistoryPoint[];
  currentIndex: number;
  onIndexChange: (index: number) => void;
  width?: number;
  height?: number;
}

export default function PlaybackSlider({
  history,
  currentIndex,
  onIndexChange,
  width = 560,
  height = 64,
}: Props) {
  const margin = { top: 4, right: 12, bottom: 20, left: 12 };
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
        .scaleLinear()
        .domain([0, parsed.length - 1])
        .range([0, innerW]),
    [parsed.length, innerW],
  );

  const yScale = useMemo(
    () =>
      d3
        .scaleLinear()
        .domain([0, 100])
        .range([innerH, 0]),
    [innerH],
  );

  const area = useMemo(
    () =>
      d3
        .area<(typeof parsed)[0]>()
        .x((_, i) => xScale(i))
        .y0(innerH)
        .y1((d) => yScale(d.score))
        .curve(d3.curveMonotoneX),
    [xScale, yScale, innerH],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onIndexChange(Number(e.target.value));
    },
    [onIndexChange],
  );

  if (parsed.length < 2) return null;

  const first = parsed[0];
  const last = parsed[parsed.length - 1];
  if (!first || !last) return null;

  const current = parsed[currentIndex] ?? first;
  const dateLabel = d3.timeFormat("%b %d, %Y")(current.date);
  const thumbX = xScale(currentIndex);

  return (
    <div className="relative" style={{ width }}>
      {/* Sparkline background */}
      <svg width={width} height={height} className="pointer-events-none">
        <g transform={`translate(${margin.left},${margin.top})`}>
          <path d={area(parsed) ?? ""} fill="rgba(59,130,246,0.12)" />

          {/* Playhead line */}
          <line
            x1={thumbX}
            x2={thumbX}
            y1={0}
            y2={innerH}
            stroke="rgba(59,130,246,0.6)"
            strokeWidth={2}
            strokeDasharray="4 2"
          />

          {/* Current value badge */}
          <circle
            cx={thumbX}
            cy={yScale(current.score)}
            r={4}
            fill="#3b82f6"
            stroke="#0f172a"
            strokeWidth={2}
          />
        </g>
      </svg>

      {/* HTML range input overlaid */}
      <input
        type="range"
        min={0}
        max={parsed.length - 1}
        value={currentIndex}
        onChange={handleChange}
        className="absolute inset-0 w-full opacity-0 cursor-pointer"
        style={{ height }}
      />

      {/* Date & score label */}
      <div className="flex items-center justify-between mt-1 px-3">
        <span className="text-xs text-gray-500">
          {d3.timeFormat("%b %Y")(first.date)}
        </span>
        <span className="text-xs font-medium text-blue-400">
          {dateLabel} — CESI {current.score.toFixed(1)}
        </span>
        <span className="text-xs text-gray-500">
          {d3.timeFormat("%b %Y")(last.date)}
        </span>
      </div>
    </div>
  );
}
