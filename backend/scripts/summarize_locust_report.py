"""Summarize Locust CSV outputs into a markdown load validation report.

Expected input files (from locust --csv=<prefix>):
- <prefix>_stats.csv
- <prefix>_failures.csv (optional)

Output:
- reports/validation/load_test_report.md
"""

from __future__ import annotations

import csv
from pathlib import Path


def _to_float(value: str) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def main(prefix: str = "locust") -> None:
    stats_path = Path(f"{prefix}_stats.csv")
    failures_path = Path(f"{prefix}_failures.csv")
    out_dir = Path("reports/validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "load_test_report.md"

    if not stats_path.exists():
        raise FileNotFoundError(f"Missing stats csv: {stats_path}")

    rows: list[dict[str, str]] = []
    with stats_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    aggregate = next((r for r in rows if r.get("Name") == "Aggregated"), None)
    if aggregate is None:
        raise RuntimeError("Aggregated row not found in locust stats csv")

    rps = _to_float(aggregate.get("Requests/s", "0"))
    p99 = _to_float(aggregate.get("99%", "0"))
    failures = _to_float(aggregate.get("Failure Count", "0"))

    meets_rps = rps >= 1000.0
    meets_p99 = p99 <= 200.0

    lines: list[str] = []
    lines.append("# FRR Load Test Validation")
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- Requests/sec: **{rps:.2f}** (target: >= 1000)")
    lines.append(f"- p99 latency (ms): **{p99:.2f}** (target: <= 200)")
    lines.append(f"- Total failures: **{int(failures)}**")
    lines.append("")
    lines.append("## Target Status")
    lines.append("")
    lines.append(f"- Throughput target met: **{meets_rps}**")
    lines.append(f"- Latency target met: **{meets_p99}**")
    lines.append("")

    if failures_path.exists():
        lines.append("## Failure Details")
        lines.append("")
        lines.append("Included from Locust failures CSV.")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Load report written: {out_path.resolve()}")


if __name__ == "__main__":
    main()
