"""Generate validation artifacts from backtesting.

Outputs:
- reports/validation/backtest_summary.json
- reports/validation/backtest_summary.md
- reports/validation/calibration_curves.json
"""

# pyright: reportMissingImports=false

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = BACKEND_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from frr.scoring.backtest import run_full_backtest


def _to_markdown(data: dict) -> str:
    lines: list[str] = []
    lines.append("# FRR Backtest Validation Report")
    lines.append("")
    lines.append(f"Generated at: `{data['generated_at']}`")
    lines.append("")
    lines.append("## Core Metrics")
    lines.append("")
    lines.append(f"- Recall: **{data['summary']['recall']:.3f}**")
    lines.append(f"- Precision: **{data['summary']['precision']:.3f}**")
    lines.append(f"- F1: **{data['summary']['f1']:.3f}**")
    lines.append(f"- Avg lead time (months): **{data['summary']['avg_lead_time_months']:.2f}**")
    lines.append(f"- Avg Brier score: **{data['summary']['avg_brier_score']:.4f}**")
    lines.append(f"- Avg Brier skill score: **{data['summary']['avg_brier_skill_score']:.4f}**")
    lines.append(f"- Avg ROC AUC: **{data['summary']['avg_auc']:.4f}**")
    lines.append("")

    lines.append("## Per-crisis Brier Scores")
    lines.append("")
    lines.append("| Crisis Type | Brier | Baseline | Brier Skill | Samples |")
    lines.append("|---|---:|---:|---:|---:|")
    for row in data["brier_scores"]:
        lines.append(
            f"| {row['crisis_type']} | {row['brier_score']:.5f} | {row['naive_baseline']:.5f} | {row['brier_skill_score']:.5f} | {row['n_samples']} |"
        )
    lines.append("")

    lines.append("## Per-crisis ROC")
    lines.append("")
    lines.append("| Crisis Type | AUC | Optimal Threshold | TPR | FPR |")
    lines.append("|---|---:|---:|---:|---:|")
    for row in data["roc_results"]:
        lines.append(
            f"| {row['crisis_type']} | {row['auc']:.4f} | {row['optimal_threshold']:.3f} | {row['tpr_at_optimal']:.3f} | {row['fpr_at_optimal']:.3f} |"
        )
    lines.append("")

    lines.append("## Known Crisis Validations")
    lines.append("")
    lines.append("| Crisis | Region | Detected | Lead Months | Peak CESI | Met Target |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for row in data["known_crisis_validations"]:
        lines.append(
            f"| {row['crisis']} | {row['region']} | {str(row['detected'])} | {row['lead_months']:.1f} | {row['peak_cesi']:.1f} | {str(row['met_target'])} |"
        )

    return "\n".join(lines) + "\n"


async def main() -> None:
    out_dir = Path("reports/validation")
    out_dir.mkdir(parents=True, exist_ok=True)

    result = await run_full_backtest(start_year=2015, end_year=2024)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "recall": result.recall,
            "precision": result.precision,
            "f1": result.f1,
            "avg_lead_time_months": result.avg_lead_time_months,
            "avg_brier_score": result.avg_brier_score,
            "avg_brier_skill_score": result.avg_brier_skill_score,
            "avg_auc": result.avg_auc,
            "total_crises": result.total_crises,
            "detected": result.detected,
            "false_alarms": result.false_alarms,
        },
        "brier_scores": [asdict(x) for x in result.brier_scores],
        "roc_results": [asdict(x) for x in result.roc_results],
        "known_crisis_validations": result.known_crisis_validations,
        "calibration_curves": result.calibration_curves,
    }

    (out_dir / "backtest_summary.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    (out_dir / "calibration_curves.json").write_text(
        json.dumps(payload["calibration_curves"], indent=2),
        encoding="utf-8",
    )
    (out_dir / "backtest_summary.md").write_text(
        _to_markdown(payload),
        encoding="utf-8",
    )

    print(f"Validation artifacts written to: {out_dir.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
