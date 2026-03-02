/** Utility functions for the frontend. */

/** Map a severity string to a Tailwind CSS class. */
export function severityClass(severity: string | null): string {
  switch (severity) {
    case "stable":
      return "severity-stable";
    case "elevated":
      return "severity-elevated";
    case "concerning":
      return "severity-concerning";
    case "high_risk":
      return "severity-high-risk";
    case "critical":
      return "severity-critical";
    default:
      return "bg-gray-500/20 text-gray-400";
  }
}

/** Map a severity string to a colour hex for deck.gl / d3. */
export function severityColor(severity: string | null): [number, number, number] {
  switch (severity) {
    case "stable":
      return [34, 197, 94];    // green-500
    case "elevated":
      return [234, 179, 8];    // yellow-500
    case "concerning":
      return [249, 115, 22];   // orange-500
    case "high_risk":
      return [239, 68, 68];    // red-500
    case "critical":
      return [220, 38, 38];    // red-600
    default:
      return [107, 114, 128];  // gray-500
  }
}

/** Format a CESI score for display. */
export function formatCESI(score: number): string {
  return score.toFixed(1);
}

/** Format a probability (0-1) as a percentage string. */
export function formatProbability(p: number): string {
  return `${(p * 100).toFixed(1)}%`;
}
